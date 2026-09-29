FROM backend-runtime
ENV LIFEREEL_SERVICE=interview SERVICE_MODE=distributed
COPY services/interview/app.py /app/app.py
WORKDIR /app
EXPOSE 8000
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
