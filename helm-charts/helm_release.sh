#!/bin/sh -x

rm -r index.yaml
rm -r jenkins-jobmon-*.tgz

helm package jenkins-jobmon

helm repo index .
