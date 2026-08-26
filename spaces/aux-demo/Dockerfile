FROM python:3.12-slim

RUN useradd --create-home --uid 1000 user
WORKDIR /home/user/app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=user:user . .
USER user

ENV GRADIO_SERVER_NAME=0.0.0.0
ENV GRADIO_SERVER_PORT=7860
EXPOSE 7860

CMD ["python", "app.py"]
