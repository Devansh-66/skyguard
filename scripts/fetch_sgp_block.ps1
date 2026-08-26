# Download contemporaneous SGP coverage, which is what neighbour differencing needs.
#
# WHY THIS IS NEEDED
#
# The existing corpus was downloaded one fault window at a time, so the SGP
# stations almost never overlap in time. Measured: of 67 SGP days held, 45 have
# only ONE station reporting. Neighbour differencing has nothing to compare
# against on those days, so the evaluation could not run at all -- it reported
# "no station/sensor had both clean and faulty periods".
#
# The fix is coverage of the same DATES across all stations, not more fault
# windows. Two blocks, chosen for what each can prove.
#
#   BLOCK A -- one station faulty, six healthy neighbours.
#   sgpmetE13 carries a DQR from 2015-11-30 to 2015-12-04 affecting temperature,
#   pressure, humidity AND both housekeeping channels, and no other SGP station
#   is flagged in that month. That is the clean test: does the belief state move
#   for the broken station while its healthy neighbours provide the reference?
#
#   BLOCK B -- six stations faulty at once.
#   On 2020-10-26 to 2020-10-29, E13, E31, E32, E37, E39 and E41 ALL carry a DQR
#   for the same window and the same variables. That is a correlated fleet
#   failure in real data, and it is the case this project has argued is
#   invisible to every neighbour-based method including IMD's, because the
#   neighbours agree with each other while all of them are wrong. Downloading it
#   lets that limitation be DEMONSTRATED rather than asserted.
#
# Each block includes surrounding clean time, because a reference built only
# from the fault period would be self-masked in exactly the way this whole
# exercise is trying to avoid.
#
# Credentials are read from the environment and never written here.
#   $env:ARM_USER='...'; $env:ARM_TOKEN='...'
#
# Rough size: 7 stations x ~105 days ~= 700 daily files, on the order of 150 MB.
# The downloader resumes safely, so this can be interrupted and re-run.

$ErrorActionPreference = "Stop"

if (-not $env:ARM_USER -or -not $env:ARM_TOKEN) {
    Write-Error "Set ARM_USER and ARM_TOKEN first. They are read from the environment and never stored in this repo."
    exit 1
}

$stations = @("sgpmetE13.b1", "sgpmetE31.b1", "sgpmetE32.b1", "sgpmetE33.b1",
              "sgpmetE37.b1", "sgpmetE39.b1", "sgpmetE41.b1")

$blocks = @(
    @{ Name = "A: one station faulty, neighbours healthy"; Start = "2015-11-15"; End = "2015-12-20" },
    @{ Name = "B: six stations faulty at once (fleet failure)"; Start = "2020-10-10"; End = "2020-11-15" }
)

foreach ($b in $blocks) {
    Write-Host ""
    Write-Host "=== Block $($b.Name)" -ForegroundColor Cyan
    Write-Host "    $($b.Start) to $($b.End), $($stations.Count) stations"
    foreach ($s in $stations) {
        Write-Host "  -> $s"
        python -m scripts.arm_download $s $b.Start $b.End
    }
}

Write-Host ""
Write-Host "Done. Now re-run the evaluation against the neighbour reference:" -ForegroundColor Green
Write-Host "  python -m evaluation.run_ai_arm --reference neighbour"
Write-Host ""
Write-Host "And compare it against the self-masking one, which is the point:" -ForegroundColor Green
Write-Host "  python -m evaluation.run_ai_arm --reference trailing"
