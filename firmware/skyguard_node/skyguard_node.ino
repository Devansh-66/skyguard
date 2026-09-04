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
#include <Wire.h>
#include <Adafruit_BME280.h>
#include <ArduinoJson.h>
#include <math.h>

// Wokwi's virtual access point. Open network, empty password, connects fast.
static const char* WIFI_SSID = "Wokwi-GUEST";
static const char* WIFI_PASS = "";

// host.wokwi.internal is the simulated node's route to a service on the host
// machine. Change to a LAN address or a real hostname for hardware.
static const char* SERVER = "http://host.wokwi.internal:8000";
static const char* STATION = "Pune";
static const char* FW_VERSION = "skyguard-node-1.0.0";

static const uint32_t SAMPLE_MS = 2000;      // demo cadence; 15 min in the field
static const uint32_t HEARTBEAT_EVERY = 15;  // samples between forced uplinks

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

static inline uint8_t pct64(uint64_t bits, uint8_t fill) {
  if (!fill) return 0;
  return (uint8_t)((__builtin_popcountll(bits) * 100) / fill);
}

// Supply in millivolts. The divider halves it, and the ESP32 ADC is 12-bit
// over a nominal 3.3 V reference.
static uint16_t readVbatMv() {
  const uint32_t raw = analogRead(PIN_VBAT);
  return (uint16_t)((raw * 3300UL * 2UL) / 4095UL);
}

// Logger temperature in 1/100 C, mapped from the pot across -40..85 C.
static int16_t readLogTempC100() {
  const uint32_t raw = analogRead(PIN_LOGTEMP);
  return (int16_t)(-4000 + (int32_t)((raw * 12500L) / 4095L));
}

Adafruit_BME280 bme;
bool haveSensor = false;

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

static void fetchBaseline() {
  HTTPClient http;
  http.begin(String(SERVER) + "/api/baseline/" + STATION);
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
  http.begin(String(SERVER) + "/api/ingest");
  http.addHeader("Content-Type", "application/json");

  StaticJsonDocument<512> doc;
  doc["station"] = STATION;
  doc["temp"] = t; doc["rh"] = h; doc["pres"] = p;
  doc["seq"] = seq;
  doc["dt_min"] = SAMPLE_MS / 60000.0f;   // the node's frame, not arrival time
  doc["fw"] = FW_VERSION;

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

  Wire.begin(21, 22);
  haveSensor = bme.begin(0x76) || bme.begin(0x77);
  Serial.println(haveSensor ? "BME280 ok" : "BME280 NOT FOUND -- check wiring");
  if (!haveSensor) selftestMask |= ST_NO_ACK;

  // Boot self-test. A set bit is a failed check; the server turns the mask
  // into checks_passed and the hardware agent branches on it.
  if (haveSensor) {
    const float t0 = bme.readTemperature();
    const float h0 = bme.readHumidity();
    const float p0 = bme.readPressure() / 100.0f;
    if (isnan(t0) || isnan(h0) || isnan(p0)) selftestMask |= ST_NONFINITE;
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

  float t = bme.readTemperature();
  float h = bme.readHumidity();
  float p = bme.readPressure() / 100.0f;   // Pa -> hPa

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

  const float dtMin = SAMPLE_MS / 60000.0f;
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

  Serial.printf("[%lu] T=%.2f RH=%.1f P=%.1f %s\n", (unsigned long)seq, t, h, p,
                flagged ? ("FLAG " + flags).c_str() : "");

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
