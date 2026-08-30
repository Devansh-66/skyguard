# The detector, for a Hugging Face Space (or any container host).
#
# WHAT IS AND IS NOT IN THIS IMAGE
#
# In: the API, the simulated network, and the precomputed ARM queue.
# Out: the 138 MB ARM netCDF archive. Building the maintenance board reads 591
#      files to produce 200 kB of answer, and that answer cannot change -- the
#      archive is closed and the analyst reports are written. So the answer
#      ships and the question does not. `python -m scripts.export_queue`
#      regenerates it on a machine that has the archive.
#
# The simulated network is NOT frozen this way. It is graded on every request,
# and it is the path live readings will arrive on over MQTT.
FROM python:3.11-slim

# Hugging Face Spaces run as uid 1000 and serve on 7860.
ENV PYTHONUNBUFFERED=1 \
    PORT=7860 \
    HOME=/home/user
RUN useradd -m -u 1000 user
WORKDIR /home/user/app

COPY --chown=user requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=user api/ ./api/
COPY --chown=user detect/ ./detect/
COPY --chown=user physics/ ./physics/
COPY --chown=user learn/ ./learn/
COPY --chown=user simulate/ ./simulate/
COPY --chown=user scripts/ ./scripts/
COPY --chown=user dashboard/ ./dashboard/
COPY --chown=user models/ ./models/

# The simulated network, built at IMAGE BUILD TIME rather than on boot: it takes
# about eighty seconds, and a Space that spends eighty seconds starting looks
# broken to whoever opened the link.
RUN python -m simulate.network && python -m simulate.faults_and_export

USER user
EXPOSE 7860
CMD ["python", "-m", "uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "7860"]
