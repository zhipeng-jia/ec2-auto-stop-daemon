#!/bin/bash

BASE_DIR=`dirname $0`

if [[ $EUID -ne 0 ]]; then
    echo "This script must be run as root" 
    exit 1
fi

AWS_REGION=`awk -F" = " '/^region/ { print $2 }' $HOME/.aws/config 2>/dev/null`
AWS_ACCESS_KEY_ID=`awk -F" = " '/^aws_access_key_id/ { print $2 }' $HOME/.aws/credentials 2>/dev/null`
AWS_SECRET_ACCESS_KEY=`awk -F" = " '/^aws_secret_access_key/ { print $2 }' $HOME/.aws/credentials 2>/dev/null`
if [ -z $AWS_REGION ]; then
    read -e -p "Enter AWS region: " AWS_REGION
fi
if [ -z $AWS_ACCESS_KEY_ID ]; then
    read -e -p "Enter AWS access key ID: " AWS_ACCESS_KEY_ID
fi
if [ -z $AWS_SECRET_ACCESS_KEY ]; then
    read -es -p "Enter AWS secret access key: " AWS_SECRET_ACCESS_KEY
fi

cp $BASE_DIR/main.py /usr/local/bin/ec2-auto-stop-daemon
cp $BASE_DIR/systemd/ec2-auto-stop-daemon.service /etc/systemd/system
mkdir -p /etc/ec2-auto-stop-daemon
cp $BASE_DIR/config.sample.json /etc/ec2-auto-stop-daemon/config.json
chmod 0600 /etc/ec2-auto-stop-daemon/config.json

sed -i "s/<AWS_REGION>/$AWS_REGION/g" /etc/ec2-auto-stop-daemon/config.json
sed -i "s/<AWS_ACCESS_KEY_ID>/$AWS_ACCESS_KEY_ID/g" /etc/ec2-auto-stop-daemon/config.json
sed -i "s/<AWS_SECRET_ACCESS_KEY>/$AWS_SECRET_ACCESS_KEY/g" /etc/ec2-auto-stop-daemon/config.json

systemctl enable ec2-auto-stop-daemon
systemctl stop ec2-auto-stop-daemon
systemctl start ec2-auto-stop-daemon
