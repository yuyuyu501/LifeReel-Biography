FROM backend-runtime
ENV LIFEREEL_SERVICE=worker-interview SERVICE_MODE=distributed
COPY workers/runtime /worker
COPY workers/interview/main.py /worker/main.py
WORKDIR /worker
CMD ["python", "main.py"]
