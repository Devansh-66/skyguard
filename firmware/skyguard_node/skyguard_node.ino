// SkyGuard station node -- the edge tier of PS26073.
//
// WHAT THIS TIER IS FOR, AND WHAT IT DELIBERATELY DOES NOT DO
//
// It runs the physics screen and nothing that needs neighbours. A station has
// no neighbours; it has a radio. Neighbour differencing, the learned stage,
// conformal p-values and signature naming all live on the server, because they
// need data this node will never hold.
//
// What it does hold is O(1) state: nine harmonic coefficients per variable
// pushed from the server, a P-square quantile sketch, and the previous sample.
// No history buffer, no model file, no ML runtime. That is what makes it fit.
//
// WHY IT NEVER FITS ITS OWN BASELINE
//
// Measured in evaluation/run_edge_approx.py: a baseline fitted on a window that
// contains a 0.02 K/day drift absorbs essentially all of it -- the fraction of
// the drift still visible in the residual afterwards is 0.035 for OLS, 0.008
// for batch Huber, 0.064 for online Huber. Robust estimators are no better,
// because a slow drift never looks like an outlier. A node that refits on its
// own data goes blind to the exact fault this project exists to catch, and
// reports healthy while doing it. So the server fits on an approved window and
// pushes coefficients; this node uses them and never refits.
//
// WHY THE UPLINK IS CONDITIONAL
//
// Radio TX dominates an AWS power budget. Sending every reading is the easy
// thing and the wrong one. This node sends a reading when it is flagged or
// when the heartbeat is due, and stays quiet otherwise.
//
// BUILD: Wokwi for VS Code -- F1, "Wokwi: Start Simulator". The bundled private
// gateway lets the simulated node reach a server on this machine at
// host.wokwi.internal. See README.md in this directory.

#include <WiFi.h>
#include <HTTPClient.h>
#include <WiFiClientSecure.h>
#include <Wire.h>
// WHICH SENSOR THIS BUILD TALKS TO.
//
// The field station uses a BME280: one part, all three parameters, over I2C.
// Wokwi does not have one -- its element set is dht22, an NTC, a photoresistor
// and a handful of others, with no barometric sensor of any kind. A part named
// "wokwi-bme280" renders as a picture with nothing behind it, so the bus scan
// comes back empty and the node never takes a reading.
//
// The simulator build therefore reads temperature and humidity from a DHT22 --
// a real driver against a real device model -- and pressure from a
// potentiometer, which is a knob and is labelled as one. The hardware build is
// unchanged and still compiles from this same file.
#define SENSOR_BME280 0

#if SENSOR_BME280
#include <Adafruit_BME280.h>
#else
#include <DHT.h>
#endif
#include <ArduinoJson.h>
#include <math.h>

// Wokwi's virtual access point. Open network, empty password, connects fast.
static const char* WIFI_SSID = "Wokwi-GUEST";
static const char* WIFI_PASS = "";

// host.wokwi.internal is the simulated node's route to a service on the host
// machine. Change to a LAN address or a real hostname for hardware.
// WHERE THE READINGS GO. Pick one; the code handles either scheme.
//
//   host.wokwi.internal  resolves ONLY under the Wokwi VS Code extension,
//                        whose private gateway routes it to the developer's
//                        machine. From wokwi.com there is no such route --
//                        "localhost" there means Wokwi's own container.
//   the https URL        is the deployed Space, which IS reachable from
//                        wokwi.com, and is what the public demo uses.
//
// static const char* SERVER = "http://host.wokwi.internal:8000";
static const char* SERVER = "https://dev-66-skyguard-api.hf.space";
static const char* STATION = "WOKWI-ESP32";
// BUMP THIS WHENEVER THE SKETCH CHANGES.
//
// It is printed at boot and sent with every reading, and it is the only way to
// tell from the outside WHICH build is running. Two copies of this sketch once
// drifted apart -- one pasted into the Wokwi web editor, one in the repo -- and
// the only reason the difference was ever noticed is that their banners did not
// match. Cheap insurance.
static const char* FW_VERSION = "skyguard-node-1.3.0-simframe";

static const uint32_t SAMPLE_MS = 2000;      // demo cadence; 15 min in the field
static const uint32_t HEARTBEAT_EVERY = 15;  // samples between forced uplinks

// HOW MUCH WEATHER ONE SAMPLE REPRESENTS, WHICH IS NOT HOW LONG IT TOOK.
//
// The node samples every two seconds so a demo is watchable, but each sample
// is one frame of the simulated record -- thirty simulated minutes. Those are
// different numbers and the server needs the second one.
//
// It used to send SAMPLE_MS / 60000 = 0.033 min, so the server's rate check
// allowed a change of 3.0 C/min x 0.033 min = 0.1 C between samples, against
// sensor noise of 0.25 C and a diurnal swing far larger. Every ordinary
// reading looked like an impossible jump. The check was right; the node was
// telling it the wall clock.
//
// Set to 15.0 for a field station reporting on the WMO cadence, with the
// sample interval to match. SIM_FRAMES is the length of the record the frame
// counter wraps against.
static const float SIM_MINUTES_PER_SAMPLE = 30.0f;
static const uint32_t SIM_FRAMES = 1440;     // 30 days of 30-minute frames

// Whether this build is reporting against the simulated record at all. On real
// hardware there is no record and no frame -- the server falls back to arrival
// time, which is correct there and wrong here.
#define REPORT_SIM_FRAME 1

// ------------------------------------------------------------ housekeeping
//
// WHY A NODE MUST REPORT ITS OWN HEALTH, NOT JUST ITS READINGS
//
// The server can see that a value looks wrong. It cannot see that the supply
// sagged, that the logger is cooking, or that a sample was DUE and never
// taken -- absence of a reading is exactly the thing that does not arrive.
// Only this tier knows those, so only this tier can report them, and until it
// did the hardware-health agent on the server had nothing to judge and
// abstained on every live reading.
static const int PIN_VBAT = 34;      // divider (or pot, in Wokwi) -> supply
static const int PIN_LOGTEMP = 35;   // logger die temperature proxy
static const int PIN_FREEZE = 27;    // demo: hold to freeze the sensor
static const int PIN_CUTLINK = 26;   // demo: hold to cut the uplink
static const int PIN_DHT = 15;       // DHT22 data (simulator build)
static const int PIN_PRES = 32;      // pressure knob (simulator build), ADC1

// The knob's travel, in hPa. Deliberately inside the WMO rails: pressure is a
// stand-in here, and a stand-in that can be driven to an impossible value
// would only test the rail check against itself.
static const float PRES_LO = 950.0f, PRES_HI = 1050.0f;

// The rolling window the flat and gap percentages are computed over. 64 fits
// two uint64_t bitmasks, so both counts are a popcount and no history is kept.
static const uint8_t WIN = 64;
static uint64_t flatBits = 0, gapBits = 0;
static uint8_t  winFill = 0;

static uint16_t selftestMask = 0;
static uint32_t bootId = 0;
static uint16_t rebootCount = 0;
static const char* healthState = "S1";

// A set bit is a FAILED check.
enum : uint16_t {
  ST_NO_ACK        = 1 << 1,
  ST_BAD_CHIPID    = 1 << 2,
  ST_NONFINITE     = 1 << 4,
  ST_OUT_OF_RANGE  = 1 << 5,
  ST_TRIPLE_SAME   = 1 << 6,
  ST_CROSS_CHANNEL = 1 << 7,
  ST_HK_VBAT       = 1 << 8,
  ST_HK_LOGTEMP    = 1 << 9,
  ST_NO_LINK       = 1 << 10,
  ST_NO_BASELINE   = 1 << 11,
};

// TYPES BEFORE ANY FUNCTION, DELIBERATELY.
//
// The Arduino builder generates prototypes for every function in a .ino and
// inserts them ahead of the FIRST function definition. A function whose
// signature mentions a type declared later than that point therefore fails to
// compile with an error pointing at a comment several lines away -- which is
// exactly what happened when the housekeeping helpers were added above these
// structs: baselineValue(const Baseline&) got a prototype before `Baseline`
// existed. Keep every user-defined type above the first function.

// ---------------------------------------------------------------- rails
// A reading outside these is a broken sensor or a broken frame, not weather.
// It must never reach the detector: a sentinel averaged into a neighbour
// median corrupts every station around it.
struct Rail { float lo, hi, rate; };  // rate = largest believable change/minute
static const Rail RAIL_T = { -40.0f,  60.0f,  3.0f };
// RH's upper rail is 105, not 100: a capacitive probe reads slightly above
// saturation in fog and rain, and that is a healthy sensor, not a broken one.
static const Rail RAIL_H = {   0.0f, 105.0f, 20.0f };
static const Rail RAIL_P = { 500.0f, 1100.0f, 2.0f };

// ------------------------------------------------------- harmonic baseline
// Nine coefficients: mean, two diurnal harmonics, two annual harmonics.
// Fetched from the server, never fitted here.
struct Baseline {
  float c[9];
  bool  fitted;
};
Baseline baseT = {{0}, false}, baseH = {{0}, false}, baseP = {{0}, false};

static inline uint8_t pct64(uint64_t bits, uint8_t fill) {
  if (!fill) return 0;
  return (uint8_t)((__builtin_popcountll(bits) * 100) / fill);
}

// Supply in millivolts, 12-bit ADC over a nominal 3.3 V reference.
//
// On hardware the battery sits behind a 2:1 divider, because a LiPo above
// 3.3 V would otherwise pin the ADC. The simulator's potentiometer spans the
// 3.3 V rail directly and needs no such correction -- applying it anyway
// reported 4258 mV on a 3.3 V system, which is not a reading any real supply
// could produce and would have made the brownout threshold untestable.
#if SENSOR_BME280
static const uint32_t VBAT_NUM = 2;   // hardware: 2:1 divider
#else
static const uint32_t VBAT_NUM = 1;   // simulator: pot straight across 3V3
#endif

static uint16_t readVbatMv() {
  const uint32_t raw = analogRead(PIN_VBAT);
  return (uint16_t)((raw * 3300UL * VBAT_NUM) / 4095UL);
}

// Logger temperature in 1/100 C, mapped from the pot across -40..85 C.
static int16_t readLogTempC100() {
  const uint32_t raw = analogRead(PIN_LOGTEMP);
  return (int16_t)(-4000 + (int32_t)((raw * 12500L) / 4095L));
}

#if SENSOR_BME280
Adafruit_BME280 bme;
#else
DHT dht(PIN_DHT, DHT22);
#endif
bool haveSensor = false;



// ONE READ PATH, WHICHEVER SENSOR IS FITTED.
//
// setup() and loop() must not care which part is on the board. The difference
// between hardware and simulator is confined to these two functions.

static bool sensorBegin() {
#if SENSOR_BME280
  Wire.begin(21, 22);
  // I2C SCAN, BEFORE TRUSTING THE DRIVER. An empty bus -- wiring, power, a
  // missing part -- and a device answering at an address the driver did not
  // try are different faults with opposite fixes, and begin()'s boolean
  // cannot tell them apart.
  Serial.print("i2c:");
  uint8_t found = 0;
  for (uint8_t a = 1; a < 127; a++) {
    Wire.beginTransmission(a);
    if (Wire.endTransmission() == 0) { Serial.print(" 0x"); Serial.print(a, HEX); found++; }
  }
  if (!found) Serial.print(" nothing responded");
  Serial.println();
  return bme.begin(0x76) || bme.begin(0x77);
#else
  dht.begin();
  // The DHT22 needs a moment after power-up before its first conversion is
  // valid, and reports a failed read as NaN rather than an error code.
  delay(1200);
  return !isnan(dht.readTemperature());
#endif
}

// Fills t/h/p. Returns false when the sensor produced no usable sample, which
// is a DIFFERENT condition from a sample that is out of range: one is a dead
// probe, the other is a live probe reading something impossible.
static bool sensorRead(float& t, float& h, float& p) {
#if SENSOR_BME280
  t = bme.readTemperature();
  h = bme.readHumidity();
  p = bme.readPressure() / 100.0f;   // Pa -> hPa
#else
  t = dht.readTemperature();
  h = dht.readHumidity();
  const uint32_t raw = analogRead(PIN_PRES);
  p = PRES_LO + (PRES_HI - PRES_LO) * (raw / 4095.0f);
#endif
  return !(isnan(t) || isnan(h) || isnan(p));
}


static float baselineValue(const Baseline& b, float solarHour, float doy) {
  if (!b.fitted) return NAN;
  const float wd = 2.0f * PI * solarHour / 24.0f;
  const float wa = 2.0f * PI * doy / 365.25f;
  return b.c[0]
       + b.c[1] * sinf(wd)      + b.c[2] * cosf(wd)
       + b.c[3] * sinf(2 * wd)  + b.c[4] * cosf(2 * wd)
       + b.c[5] * sinf(wa)      + b.c[6] * cosf(wa)
       + b.c[7] * sinf(2 * wa)  + b.c[8] * cosf(2 * wa);
}

// ------------------------------------------------------- P-square sketch
// A running quantile in constant memory: five markers, no samples stored.
// Measured against an exact 720-sample median/MAD it agrees on 99.2-99.4 % of
// 3-sigma flags, for 20 floats of state instead of 720.
class P2 {
 public:
  explicit P2(float p) : p_(p), n_(0) {}
  void push(float x) {
    if (n_ < 5) {
      q_[n_++] = x;
      if (n_ == 5) {
        for (int i = 0; i < 5; i++)
          for (int j = i + 1; j < 5; j++)
            if (q_[j] < q_[i]) { float t = q_[i]; q_[i] = q_[j]; q_[j] = t; }
        for (int i = 0; i < 5; i++) { nn_[i] = i + 1; }
        np_[0] = 1; np_[1] = 1 + 2 * p_; np_[2] = 1 + 4 * p_;
        np_[3] = 3 + 2 * p_; np_[4] = 5;
        dn_[0] = 0; dn_[1] = p_ / 2; dn_[2] = p_; dn_[3] = (1 + p_) / 2; dn_[4] = 1;
      }
      return;
    }
    int k;
    if (x < q_[0]) { q_[0] = x; k = 0; }
    else if (x < q_[1]) k = 0;
    else if (x < q_[2]) k = 1;
    else if (x < q_[3]) k = 2;
    else if (x <= q_[4]) k = 3;
    else { q_[4] = x; k = 3; }

    for (int i = k + 1; i < 5; i++) nn_[i] += 1;
    for (int i = 0; i < 5; i++) np_[i] += dn_[i];

    for (int i = 1; i <= 3; i++) {
      float d = np_[i] - nn_[i];
      if ((d >= 1 && nn_[i + 1] - nn_[i] > 1) ||
          (d <= -1 && nn_[i - 1] - nn_[i] < -1)) {
        int s = (d >= 0) ? 1 : -1;
        float qp = parabolic(i, s);
        if (q_[i - 1] < qp && qp < q_[i + 1]) q_[i] = qp;
        else q_[i] = linear(i, s);
        nn_[i] += s;
      }
    }
    n_++;
  }
  float value() const { return (n_ < 5) ? (n_ ? q_[n_ / 2] : NAN) : q_[2]; }
  uint32_t count() const { return n_; }

 private:
  float parabolic(int i, int s) const {
    float a = (float)s / (nn_[i + 1] - nn_[i - 1]);
    float b = (nn_[i] - nn_[i - 1] + s) * (q_[i + 1] - q_[i]) / (nn_[i + 1] - nn_[i]);
    float c = (nn_[i + 1] - nn_[i] - s) * (q_[i] - q_[i - 1]) / (nn_[i] - nn_[i - 1]);
    return q_[i] + a * (b + c);
  }
  float linear(int i, int s) const {
    return q_[i] + s * (q_[i + s] - q_[i]) / (nn_[i + s] - nn_[i]);
  }
  float p_, q_[5], np_[5], dn_[5];
  float nn_[5];
  uint32_t n_;
};

P2 absResidMedian(0.5f);   // scale estimate: median |residual|

// ------------------------------------------------------------ node state
float prevT = NAN, prevH = NAN, prevP = NAN;
uint32_t seq = 0, sinceUplink = 0;
// CONSECUTIVE IDENTICAL READINGS, PER CHANNEL.
//
// This watched temperature alone. Pressure is the most valuable of the three:
// at 0.1 hPa resolution it essentially never repeats naturally, so a repeated
// pressure is close to proof of a stuck register, while a repeated temperature
// overnight is ordinary. Watching only the least informative channel was
// leaving the strongest signal on the floor.
uint8_t identicalT = 0;
uint8_t identicalH = 0;
uint8_t identicalP = 0;

static void addFlag(String& s, const char* f) {
  if (s.length()) s += ",";
  s += f;
}

// Returns a comma-separated flag list. Empty means the screen found nothing.
static String physicsScreen(float t, float h, float p, float dtMin) {
  String f = "";
  if (isnan(t)) addFlag(f, "temp_nonfinite");
  else if (t < RAIL_T.lo || t > RAIL_T.hi) addFlag(f, "temp_out_of_range");
  if (isnan(h)) addFlag(f, "rh_nonfinite");
  else if (h < RAIL_H.lo || h > RAIL_H.hi) addFlag(f, "rh_out_of_range");
  if (isnan(p)) addFlag(f, "pres_nonfinite");
  else if (p < RAIL_P.lo || p > RAIL_P.hi) addFlag(f, "pres_out_of_range");

  // A "dew point cannot exceed air temperature" check lived here and was
  // removed: it is unreachable. Swept over the whole valid rail box,
  // max(Td - T) is -0.039 K -- Magnus gives Td <= T identically for RH <= 100,
  // so it could only fire on rounding noise, while costing a logf() per
  // reading. Supersaturation is the check that does real work.
  if (h > 100.0f && h <= RAIL_H.hi) addFlag(f, "rh_supersaturated");

  // A rejected reading is not compared for rate: differencing against a
  // sentinel produces a bogus rate flag on top of the range flag that already
  // explains it, and the server skips it for the same reason -- running it
  // here would desynchronise the two screens and raise
  // edge_screen_disagreement on every bad reading.
  const bool rejected = f.indexOf("_out_of_range") >= 0 || f.indexOf("_nonfinite") >= 0;
  if (dtMin > 0 && !rejected) {
    if (!isnan(prevT) && fabsf(t - prevT) > RAIL_T.rate * dtMin) addFlag(f, "temp_rate");
    if (!isnan(prevH) && fabsf(h - prevH) > RAIL_H.rate * dtMin) addFlag(f, "rh_rate");
    if (!isnan(prevP) && fabsf(p - prevP) > RAIL_P.rate * dtMin) addFlag(f, "pres_rate");
  }
  // A probe that repeats a value exactly, many times, is stuck. The threshold
  // is deliberately high: at fine resolution a genuinely still hour repeats.
  if (identicalT >= 12) addFlag(f, "temp_frozen");
  if (identicalH >= 12) addFlag(f, "rh_frozen");
  if (identicalP >= 12) addFlag(f, "pres_frozen");
  return f;
}

// TLS WITHOUT A CERTIFICATE STORE, DELIBERATELY AND ONLY HERE.
//
// setInsecure() skips certificate validation. That is acceptable for a
// simulator posting public weather readings and is NOT acceptable on a
// deployed station: a real node must pin the CA, or an attacker on the path
// can rewrite observations that a forecast depends on. Flagged here rather
// than left as a quiet default.
static bool beginHttp(HTTPClient& http, const String& url) {
  if (url.startsWith("https:")) {
    static WiFiClientSecure tls;
    tls.setInsecure();
    return http.begin(tls, url);
  }
  return http.begin(url);
}


static void fetchBaseline() {
  HTTPClient http;
  beginHttp(http, String(SERVER) + "/api/baseline/" + STATION);
  const int code = http.GET();
  if (code == 200) {
    StaticJsonDocument<2048> doc;
    if (deserializeJson(doc, http.getString()) == DeserializationError::Ok) {
      const bool fitted = doc["fitted"] | false;
      JsonArray at = doc["coefs"]["temp"], ah = doc["coefs"]["rh"],
                ap = doc["coefs"]["pres"];
      for (int i = 0; i < 9; i++) {
        if (!at.isNull() && i < (int)at.size()) baseT.c[i] = at[i];
        if (!ah.isNull() && i < (int)ah.size()) baseH.c[i] = ah[i];
        if (!ap.isNull() && i < (int)ap.size()) baseP.c[i] = ap[i];
      }
      baseT.fitted = baseH.fitted = baseP.fitted = fitted;
      Serial.printf("baseline: %s\n",
                    fitted ? "fitted coefficients loaded"
                           : "none on server -- physics screen only");
    }
  } else {
    Serial.printf("baseline fetch failed (%d) -- physics screen only\n", code);
  }
  http.end();
}

static bool uplink(float t, float h, float p, const String& flags,
                   float residual, float scale) {
  HTTPClient http;
  beginHttp(http, String(SERVER) + "/api/ingest");
  http.addHeader("Content-Type", "application/json");

  StaticJsonDocument<512> doc;
  doc["station"] = STATION;
  doc["temp"] = t; doc["rh"] = h; doc["pres"] = p;
  doc["seq"] = seq;
  doc["dt_min"] = SIM_MINUTES_PER_SAMPLE;  // weather elapsed, not wall clock
  doc["fw"] = FW_VERSION;
#if REPORT_SIM_FRAME
  // WHICH MOMENT OF THE RECORD THIS READING IS FOR.
  //
  // The scenario steps the sensors one frame per sample from frame 0, so the
  // sample counter IS the frame. Sending it is what lets the server difference
  // this node against what its neighbours were doing at the same moment,
  // instead of against whatever they happen to be doing now -- and it is what
  // puts the node on the same axis as the other 344 on the dashboard.
  doc["frame"] = (uint32_t)(seq % SIM_FRAMES);
  doc["pass_no"] = (uint32_t)(seq / SIM_FRAMES);
#endif

  // The housekeeping tier. Sent every uplink because it is small and because
  // the server's hardware agent has no other source for any of it.
  doc["vbat_mv"] = readVbatMv();
  doc["log_temp_c100"] = readLogTempC100();
  doc["flat_pct"] = pct64(flatBits, winFill);
  doc["gap_pct"] = pct64(gapBits, winFill);
  doc["selftest_mask"] = selftestMask;
  doc["health"] = healthState;
  doc["boot_id"] = bootId;
  doc["reboot_count"] = rebootCount;
  if (!isnan(residual)) doc["residual"] = residual;
  if (!isnan(scale))    doc["scale"] = scale;
  JsonArray fa = doc.createNestedArray("flags");
  int from = 0;
  while (flags.length() && from <= (int)flags.length()) {
    int c = flags.indexOf(',', from);
    if (c < 0) c = flags.length();
    if (c > from) fa.add(flags.substring(from, c));
    from = c + 1;
  }

  String body;
  serializeJson(doc, body);
  const int code = http.POST(body);
  const bool ok = (code == 200);
  Serial.printf("  uplink %d %s\n", code, ok ? "" : http.errorToString(code).c_str());
  http.end();
  return ok;
}

void setup() {
  Serial.begin(115200);
  delay(200);
  Serial.println("\nSkyGuard node " + String(FW_VERSION));

  pinMode(PIN_FREEZE, INPUT_PULLUP);
  pinMode(PIN_CUTLINK, INPUT_PULLUP);

  // A NEW boot_id MEANS A REBOOT; A GAP WITHOUT ONE MEANS AN OUTAGE.
  // From the server those two are otherwise identical -- a silence -- and they
  // call for completely different work orders: one is a logger fault, the
  // other is a link or power fault.
  bootId = esp_random();

  haveSensor = sensorBegin();
  Serial.println(haveSensor ? "sensor ok" : "SENSOR NOT RESPONDING");
  if (!haveSensor) selftestMask |= ST_NO_ACK;

  // Boot self-test. A set bit is a failed check; the server turns the mask
  // into checks_passed and the hardware agent branches on it.
  if (haveSensor) {
    float t0, h0, p0;
    if (!sensorRead(t0, h0, p0)) selftestMask |= ST_NONFINITE;
    if (t0 < RAIL_T.lo || t0 > RAIL_T.hi ||
        h0 < RAIL_H.lo || h0 > RAIL_H.hi ||
        p0 < RAIL_P.lo || p0 > RAIL_P.hi) selftestMask |= ST_OUT_OF_RANGE;
    // The one check that genuinely needs all three parameters: specific
    // humidity outside 0..40 g/kg means the three channels do not describe
    // any real air, whatever each looks like alone.
    const float es = 6.112f * expf(17.62f * t0 / (243.12f + t0));
    const float e  = (h0 / 100.0f) * es;
    const float q  = 0.622f * e / (p0 - 0.378f * e) * 1000.0f;
    if (!(q >= 0.0f && q <= 40.0f)) selftestMask |= ST_CROSS_CHANNEL;
  }
  const uint16_t vb = readVbatMv();
  if (vb < 3100) selftestMask |= ST_HK_VBAT;
  const int16_t lt = readLogTempC100();
  if (lt < -4000 || lt > 8500) selftestMask |= ST_HK_LOGTEMP;
  Serial.print("selftest mask=0x");
  Serial.println(selftestMask, HEX);

  WiFi.begin(WIFI_SSID, WIFI_PASS);
  Serial.print("wifi");
  while (WiFi.status() != WL_CONNECTED) { delay(200); Serial.print("."); }
  Serial.println(" " + WiFi.localIP().toString());

  fetchBaseline();
}

void loop() {
  if (!haveSensor) { delay(SAMPLE_MS); return; }

  float t, h, p;
  if (!sensorRead(t, h, p)) {
    // A failed read is not a reading with a bad value in it. Say so, count it
    // against the window the way a missed sample is counted, and do not
    // manufacture a number to keep the record tidy.
    Serial.println("  sensor read failed");
    gapBits = (gapBits << 1) | 1ULL;
    if (winFill < WIN) winFill++;
    delay(SAMPLE_MS);
    return;
  }

  // DEMO CONTROLS, and why they are honest.
  //
  // Holding FREEZE makes the node repeat its last reading -- which is exactly
  // what a stuck probe does. The node is not told it is faulty and no flag is
  // planted: it has to notice the repetition itself, through the same counters
  // that would catch real hardware. Same for CUTLINK, which drops the uplink
  // and lets the gap counter discover it. A judge can create every fault class
  // the panel detects, by hand, and watch the board react to it.
  const bool freeze  = digitalRead(PIN_FREEZE)  == LOW;
  const bool cutlink = digitalRead(PIN_CUTLINK) == LOW;
  if (freeze && !isnan(prevT)) { t = prevT; h = prevH; p = prevP; }

  if (!isnan(prevT) && t == prevT) { if (identicalT < 255) identicalT++; }
  else identicalT = 0;
  if (!isnan(prevH) && h == prevH) { if (identicalH < 255) identicalH++; }
  else identicalH = 0;
  if (!isnan(prevP) && p == prevP) { if (identicalP < 255) identicalP++; }
  else identicalP = 0;

  // Roll the 64-sample window. A "flat" sample repeated on any channel; a
  // "gap" sample is one whose uplink did not land, set retroactively below.
  const bool flatNow = (identicalT > 0) || (identicalH > 0) || (identicalP > 0);
  flatBits = (flatBits << 1) | (flatNow ? 1ULL : 0ULL);
  gapBits  = (gapBits  << 1);
  if (winFill < WIN) winFill++;

  // The SAME interval the uplink declares. When these two disagree the node
  // screens against one clock and the server against another, every reading
  // comes back edge_screen_disagreement, and the marker that is supposed to
  // mean "this node's screen has failed" means "the demo is compressed".
  const float dtMin = SIM_MINUTES_PER_SAMPLE;
  const String flags = physicsScreen(t, h, p, dtMin);

  // Residual against the pushed baseline. Solar hour and day-of-year would come
  // from an RTC or GPS in the field; the simulator has no clock, so they are
  // derived from uptime purely to exercise the path.
  const float solarHour = fmodf(millis() / 1000.0f / 3600.0f, 24.0f);
  const float doy = 1.0f;
  float residual = NAN, scale = NAN;
  const float bt = baselineValue(baseT, solarHour, doy);
  if (!isnan(bt)) {
    residual = t - bt;
    absResidMedian.push(fabsf(residual));
    // 1.4826 * median|r| is the MAD estimate of sigma for a normal.
    if (absResidMedian.count() >= 5) scale = 1.4826f * absResidMedian.value();
  }

  seq++; sinceUplink++;
  const bool flagged = flags.length() > 0;
  const bool due = sinceUplink >= HEARTBEAT_EVERY;

  // THE LINE THAT MAKES THE NODE DEBUGGABLE.
  //
  // Readings alone do not explain behaviour. vbat, flat and gap are what the
  // server's hardware agent judges, and the link state is why an uplink did or
  // did not happen -- without them "no uplink" is indistinguishable from "the
  // uplink failed", which is the exact confusion this line was added to end.
  Serial.print("["); Serial.print(seq); Serial.print("] T=");
  Serial.print(t, 2); Serial.print(" RH="); Serial.print(h, 1);
  Serial.print(" P="); Serial.print(p, 1);
  Serial.print(" vbat="); Serial.print(readVbatMv());
  Serial.print(" flat="); Serial.print(pct64(flatBits, winFill));
  Serial.print("% gap="); Serial.print(pct64(gapBits, winFill));
  Serial.print("%");
  if (cutlink) Serial.print(" [LINK CUT]");
  if (flagged) { Serial.print(" FLAG "); Serial.print(flags); }
  Serial.println();

  // Conditional uplink: radio TX dominates the power budget, so a clean
  // reading between heartbeats is simply not sent.
  if (flagged || due) {
    // A cut link is a FAILED uplink, not a skipped one: the node still took
    // the sample, so the gap belongs in the window and the server should watch
    // the station go quiet rather than receive a tidy record with a hole in it.
    const bool sent = !cutlink && uplink(t, h, p, flags, residual, scale);
    if (sent) sinceUplink = 0;
    else      gapBits |= 1ULL;   // this sample's slot in the rolling window
  }

  prevT = t; prevH = h; prevP = p;
  delay(SAMPLE_MS);
}
