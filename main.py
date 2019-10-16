#!/usr/bin/python3

import os
import sys
import time
import json
import argparse
import logging
import datetime
import subprocess as sp

def check_command(command):
    ret = sp.run(['which', command], stdout=sp.PIPE, stderr=sp.PIPE)
    return ret.returncode == 0

def get_instance_id():
    ret = sp.run(['curl', '-m', '1', 'http://169.254.169.254/latest/meta-data/instance-id'],
                 stdout=sp.PIPE, stderr=sp.PIPE, encoding='utf8')
    if ret.returncode == 0:
        return ret.stdout.strip()
    else:
        return None

def stop_instances(aws_cli_path, aws_settings, instance_id, hibernate):
    cmd = [aws_cli_path, '--region', aws_settings['region'], '--output', 'json',
           'ec2', 'stop-instances', '--instance-ids', instance_id]
    if hibernate:
        cmd.append('--hibernate')
    ret = sp.run(cmd, stdout=sp.PIPE, stderr=sp.PIPE, env={
        'AWS_ACCESS_KEY_ID': aws_settings['access_key_id'],
        'AWS_SECRET_ACCESS_KEY': aws_settings['secret_access_key']
    })
    return ret.returncode == 0

def get_launch_time(aws_cli_path, aws_settings, instance_id):
    ret = sp.run([aws_cli_path, '--region', aws_settings['region'], '--output', 'json',
                  'ec2', 'describe-instances', '--instance-ids', instance_id],
                 stdout=sp.PIPE, stderr=sp.PIPE, encoding='utf8', env={
                     'AWS_ACCESS_KEY_ID': aws_settings['access_key_id'],
                     'AWS_SECRET_ACCESS_KEY': aws_settings['secret_access_key']
                 })
    if ret.returncode == 0:
        output = json.loads(ret.stdout)
        time_str = output['Reservations'][0]['Instances'][0]['LaunchTime']
        time_str = time_str[:-1]  # remove last 'Z'
        time_str = time_str + '000 +0000'
        launch_time = datetime.datetime.strptime(time_str, '%Y-%m-%dT%H:%M:%S.%f %z')
        return launch_time.timestamp()
    else:
        logging.info(ret.stderr)
        return None

def find_login_users():
    results = []
    ret = sp.run(['who'], stdout=sp.PIPE, stderr=sp.PIPE, encoding='utf8')
    if ret.returncode == 0:
        for line in ret.stdout.splitlines():
            parts = line.split()
            results.append({'user': parts[0], 'tty': parts[1]})
    return results

def find_most_recent_tty_access():
    login_users = find_login_users()
    latest_timestamp = { 'file': '', 'timestamp': 0 }
    for entry in login_users:
        tty_file = '/dev/' + entry['tty']
        if os.path.exists(tty_file):
            statinfo = os.stat(tty_file)
            if statinfo.st_atime > latest_timestamp['timestamp']:
                latest_timestamp['timestamp'] = statinfo.st_atime
                latest_timestamp['file'] = tty_file
    return latest_timestamp

def update_latest_timestamp(latest_timestamp, file_path, statinfo):
    t = max(statinfo.st_atime, statinfo.st_mtime)
    if t > latest_timestamp['timestamp']:
        latest_timestamp['timestamp'] = t
        latest_timestamp['file'] = file_path

def max_timestamp(timestamp1, timestamp2):
    if timestamp1['timestamp'] > timestamp2['timestamp']:
        return timestamp1
    else:
        return timestamp2

def scan_for_latest_timestamp(file_path):
    latest_timestamp = { 'file': '', 'timestamp': 0 }
    if os.path.isdir(file_path) or os.path.isfile(file_path):
        update_latest_timestamp(latest_timestamp, file_path, os.stat(file_path))
    if os.path.isdir(file_path):
        with os.scandir(file_path) as it:
            for entry in it:
                if entry.is_symlink():
                    continue
                if entry.is_file():
                    update_latest_timestamp(latest_timestamp, entry.path, entry.stat())
                elif entry.is_dir():
                    latest_timestamp = max_timestamp(latest_timestamp, scan_for_latest_timestamp(entry.path))
    return latest_timestamp

def last_active_timestamp(watch_paths):
    timestamp = { 'file': '', 'timestamp': 0 }
    if os.path.exists('/var/run/utmp'):
        timestamp = max_timestamp(timestamp, scan_for_latest_timestamp('/var/run/utmp'))
    else:
        logging.error('/var/run/utmp does not exist!')
    timestamp = max_timestamp(timestamp, find_most_recent_tty_access())
    for entry in watch_paths:
        if os.path.exists(entry):
            timestamp = max_timestamp(timestamp, scan_for_latest_timestamp(entry))
    return timestamp

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--config-file', required=True, help='Path to the config file')
    parser.add_argument('--log-file', default=None, help='Path to the log file')
    args = parser.parse_args()

    logging_config = {
        'level': logging.INFO,
        'format': '%(asctime)s  [%(levelname)s]  %(message)s',
        'datefmt': '%Y-%m-%d %H:%M:%S'
    }
    if args.log_file is not None:
        logging_config['filename'] = args.log_file
        logging_config['filemode'] = 'a'
    logging.basicConfig(**logging_config)

    with open(args.config_file) as fin:
        config = json.load(fin)

    if not check_command('curl'):
        logging.error('curl is not installed!')
        sys.exit(1)
    aws_cli_path = 'aws'
    if 'aws_cli_path' in config:
        aws_cli_path = config['aws_cli_path']
    if not check_command(aws_cli_path):
        logging.error('aws-cli is not installed!')
        sys.exit(1)
    if 'aws_settings' not in config:
        logging.error('Missing "aws_settings" in config!')
        sys.exit(1)
    else:
        aws_settings = config['aws_settings']

    instance_id = get_instance_id()
    if instance_id is None:
        logging.error('Failed to get instance ID of current machine!')
        sys.exit(1)

    watch_paths = []
    if 'watch_paths' in config:
        watch_paths = config['watch_paths']
        logging.info('Watch paths: ' + ', '.join(watch_paths))
    hibernate = False
    if 'hibernate' in config and config['hibernate']:
        hibernate = True
        logging.info('Enable hibernation')
    max_idle_minutes = 15
    if 'max_idle_minutes' in config:
        max_idle_minutes = config['max_idle_minutes']
        logging.info('Max idle time is %.1f minutes' % (float(max_idle_minutes),))

    while True:
        launch_time = get_launch_time(aws_cli_path, aws_settings, instance_id)
        if launch_time is not None:
            launch_duration = time.time() - launch_time
            logging.info('Machine has started for %.1f seconds' % (launch_duration,))
            if launch_duration < max_idle_minutes * 60:
                time.sleep(max_idle_minutes * 60 - launch_duration)
        else:
            logging.error('Failed to get launch time of current machine!')

        while True:
            timestamp = last_active_timestamp(watch_paths)
            idle_time = time.time() - timestamp['timestamp']
            if idle_time >= max_idle_minutes * 60:
                logging.warning('No activity for last %d minutes!' % (max_idle_minutes,))
                logging.warning('About to stop current instance.')
                if not stop_instances(aws_cli_path, aws_settings, instance_id, hibernate):
                    logging.error('Failed to stop current instance!')
                time.sleep(max_idle_minutes * 60)
                break
            else:
                logging.info('File %s accessed within %.1f seconds' % (timestamp['file'], idle_time))
                time.sleep(max_idle_minutes * 60 - idle_time)
