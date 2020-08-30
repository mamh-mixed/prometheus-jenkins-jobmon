# Jenkins Jobmon 

Jenkins exporter for Prometheus in python. It uses [Prometheus custom collector API](https://github.com/prometheus/client_python#custom-collectors), which allows making custom collectors by proxying metrics from other systems.

# Configuration 

- Create a file `config.yml` using this template:
```yaml
jobs:
  example:          # Put your repo name here
    team: example   # Put your team name
```
- Replace `team name` and `repo name` with the repos to be monitored.

# Usage

## Helm

- Create a kubernetes ConfigMap from `config.yml`:
```
kubectl create configmap jenkins-jobmon-config --from-file=config.yml
```

- Create a kubernetes secret:
```
kubectl create secret generic jenkins-jobmon-secrets --from-literal=username=username --from-literal=password=password

```
- Run following commands:

```
helm repo add jenkins-jobmon https://raw.githubusercontent.com/grofers/jenkins-jobmon/master/helm-charts
```

```
helm install jenkins-jobmon/jenkins-jobmon --generate-name \
    --set config.jenkinsServer=http://jenkins.example.com \
    --set config.secretName=jenkins-jobmon-secrets \
    --set config.configMapName=jenkins-jobmon-config \
    --set image.repository=$IMAGE \
    --set image.tag=$TAG
```

## Docker

```
docker build -t $(IMAGENAME):$(TAG) .

docker run -p 9118:9118 \
    -e JENKINS_SERVER=http://jenkins.example.com \
    -e JENKINS_USER=username \
    -e JENKINS_PASSWORD=password \
    -v /usr/src/app/config.yml:$(pwd)/config.yml $IMAGE:$TAG \
```
