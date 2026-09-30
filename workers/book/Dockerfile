FROM backend-runtime
ENV LIFEREEL_SERVICE=worker-book SERVICE_MODE=distributed
COPY workers/runtime /worker
COPY workers/book/main.py /worker/main.py
WORKDIR /worker
CMD ["python", "main.py"]
