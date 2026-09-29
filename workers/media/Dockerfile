FROM backend-runtime
ENV LIFEREEL_SERVICE=worker-media SERVICE_MODE=distributed
COPY workers/runtime /worker
COPY workers/media/main.py /worker/main.py
WORKDIR /worker
CMD ["python", "main.py"]
