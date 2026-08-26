# Clean-period ARM pull. Set your credentials first:
#   $env:ARM_USER='your-arm-id'
#   $env:ARM_TOKEN='token from https://adc.arm.gov/armlive/home'
# Windows here touch NO human-flagged fault interval.
if (-not $env:ARM_USER -or -not $env:ARM_TOKEN) {
  Write-Error 'Set ARM_USER and ARM_TOKEN first'; exit 1
}

python -m scripts.arm_download enametC1.b1 2016-01-10 2016-01-31
python -m scripts.arm_download enametC1.b1 2018-04-10 2018-05-01
python -m scripts.arm_download enametC1.b1 2020-07-10 2020-07-31
python -m scripts.arm_download enametC1.b1 2024-10-10 2024-10-31
python -m scripts.arm_download nsametC1.b1 2016-01-10 2016-01-31
python -m scripts.arm_download nsametC1.b1 2018-04-10 2018-05-01
python -m scripts.arm_download nsametC1.b1 2020-07-10 2020-07-31
python -m scripts.arm_download nsametC1.b1 2023-10-10 2023-10-31
python -m scripts.arm_download sgpmetE13.b1 2016-01-10 2016-01-31
python -m scripts.arm_download sgpmetE13.b1 2018-04-10 2018-05-01
python -m scripts.arm_download sgpmetE13.b1 2020-07-10 2020-07-31
python -m scripts.arm_download sgpmetE13.b1 2022-10-10 2022-10-31
python -m scripts.arm_download sgpmetE31.b1 2016-01-10 2016-01-31
python -m scripts.arm_download sgpmetE31.b1 2018-04-10 2018-05-01
python -m scripts.arm_download sgpmetE31.b1 2020-07-10 2020-07-31
python -m scripts.arm_download sgpmetE31.b1 2022-10-10 2022-10-31
python -m scripts.arm_download sgpmetE32.b1 2016-01-10 2016-01-31
python -m scripts.arm_download sgpmetE32.b1 2018-04-10 2018-05-01
python -m scripts.arm_download sgpmetE32.b1 2020-07-10 2020-07-31
python -m scripts.arm_download sgpmetE32.b1 2022-10-10 2022-10-31
python -m scripts.arm_download sgpmetE33.b1 2016-01-10 2016-01-31
python -m scripts.arm_download sgpmetE33.b1 2018-04-10 2018-05-01
python -m scripts.arm_download sgpmetE33.b1 2020-07-10 2020-07-31
python -m scripts.arm_download sgpmetE33.b1 2022-10-10 2022-10-31
python -m scripts.arm_download sgpmetE37.b1 2016-01-10 2016-01-31
python -m scripts.arm_download sgpmetE37.b1 2018-04-10 2018-05-01
python -m scripts.arm_download sgpmetE37.b1 2020-07-10 2020-07-31
python -m scripts.arm_download sgpmetE37.b1 2022-10-10 2022-10-31
python -m scripts.arm_download sgpmetE39.b1 2016-01-10 2016-01-31
python -m scripts.arm_download sgpmetE39.b1 2018-04-10 2018-05-01
python -m scripts.arm_download sgpmetE39.b1 2020-07-10 2020-07-31
python -m scripts.arm_download sgpmetE39.b1 2022-10-10 2022-10-31
python -m scripts.arm_download sgpmetE41.b1 2016-01-10 2016-01-31
python -m scripts.arm_download sgpmetE41.b1 2018-04-10 2018-05-01
python -m scripts.arm_download sgpmetE41.b1 2020-07-10 2020-07-31
python -m scripts.arm_download sgpmetE41.b1 2022-10-10 2022-10-31
