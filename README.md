# Jenkins Jobmon 

Jenkins exporter for Prometheus in python. It uses [Prometheus custom collector API](https://github.com/prometheus/client_python#custom-collectors), which allows making custom collectors by proxying metrics from other systems.

# Installation 
```
git clone git@github.com:grofers/jenkins-jobmon.git
cd jenkins-jobmon
```

# Configuration 

- Create configuration file using configuration template:
    `cp config.yml.example config.yml`
- In config.yml set `team name` and `repo name`, to be monitored. 

# Usage 

## Helm 

- Create a kubernetes secret : 
```
kubectl create secret generic $(secretName) --from-literal=username=$(USERNAME) --from-literal=password=$(PASSWORD)

```
- Run following commands : 

```
helm repo add jenkins-jobmon https://raw.githubusercontent.com/grofers/jenkins-jobmon/helm-charts
```

```
helm install jenkins-jobmon/jenkins-jobmon --generate-name --set config.jenkinsServer=$(JENKINS_SERVER) --set config.secretName=$(secretName) --set image.repository=$(IMAGE) --set image.tag=$(TAG)
```

## Docker

```
docker build -t $(IMAGENAME):$(TAG) .

docker run -p 9118:9118 -e JENKINS_SERVER=$(JENKINS_SERVER) -e JENKINS_USER=$(JENKINS_USER) -e JENKINS_PASSWORD=$(JENKINS_PASSWORD) -e DEBUG=1 $(IMAGENAME):$(TAG)
```
