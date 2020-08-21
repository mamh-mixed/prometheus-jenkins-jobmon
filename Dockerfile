FROM python:3-alpine

RUN mkdir -p /usr/src/app
WORKDIR /usr/src/app

COPY requirements.txt /usr/src/app
RUN pip install --no-cache-dir -r requirements.txt

COPY jenkins_exporter /usr/src/app/jenkins_exporter
COPY config.yml /usr/src/app

EXPOSE 9118

ENTRYPOINT [ "python", "-m", "jenkins_exporter" ]
