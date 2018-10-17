#!/usr/bin/env python3
# based on shell script aws-api dependant : https://aws.amazon.com/articles/high-availability-for-amazon-vpc-nat-instances-an-example/
#
import boto3
import requests
import json
import logging
import sys
from logging.handlers import RotatingFileHandler 
import time
from pprint import pprint

import multiprocessing
from subprocess import check_output, CalledProcessError, Popen, PIPE, STDOUT


class PingLoop(object):
    """
    Instantiate a thread to check the peer is up.
    """
    
    def __init__(self, host, param, logger, routes, ec2, local):
        self.logger = logger
        self.host = host
        self.param = param
        self.routes = routes
        self.ec2 = ec2
        self.local = local
        self.pause_heartbeat = 0

    def ping_loop(self):
        while True:
            command =["ping", "-c", str(self.param['num']), "-W", str(self.param['timeout']), self.host]
            p = Popen(command, stdout=PIPE, stderr=STDOUT)
            p.wait()
            if self.pause_heartbeat == 0:
                self.logger.info("waiting for next ping... %ds", self.param['nextping'])
                time.sleep(self.param['nextping'])
                if p.returncode != 0:
                    self.logger.critical("Failed to ping: %s", p.communicate())
                    switch_routes(self.routes, self.local, self.logger, self.ec2)
                    self.pause_heartbeat = 1
                    continue
                else:
                    self.logger.info("Successfull ping : %s, count=%s, timeout=%s" % 
                            (self.host, self.param['num'], self.param['timeout']))
            else:
                if p.returncode == 0:
                    self.logger.critical("The remote_nat is back online!")
                    self.pause_heartbeat  = 0
                    continue
                self.logger.critical("The remote peer was down! Waiting 1' before I try to reach it again.")
                time.sleep(60)

def switch_routes(routes, instance, logger, ec2):
    if len(routes) > 0:
        logger.info("Switching the remote route tables to %s", instance.id)
        for r in routes:
            logger.info("Treating route : %s", r.route_table_id)
            rt = ec2.Route(r.route_table_id, '0.0.0.0/0')
            rt.replace(InstanceId=instance.id)
    else:
        logger.info("The route list is empty, no action needed")
        
def update_route_dict(vpc):
    r = { 'local': [], 'remote': [], 'expected_local': [] } 
    # local - route table currently pointing to local_nat instance
    # remote - route table currently pointing to remote_nat instance
    # expected_local - route tables mounted in current subnet (expected to be pointed to local_nat)
    for rt in vpc.route_tables.all():
        for attrs in rt.routes_attribute:
            if not ('DestinationCidrBlock' in attrs.keys() and 
                    'InstanceId' in attrs.keys()
                   ):
                continue
            if attrs['DestinationCidrBlock'] == '0.0.0.0/0':
                if attrs['InstanceId'] == local_nat.id:
                    r['local'].append(rt)
                if attrs['InstanceId'] == remote_nat.id:
                    r['remote'].append(rt)
    for sub in vpc.subnets.all():
        if sub.availability_zone == local_zone:
            for rt in vpc.route_tables.all():
                for i in rt.associations_attribute:
                    if 'SubnetId' in i.keys() and sub.subnet_id == i['SubnetId']:
                            for attrs in rt.routes_attribute:
                                if('DestinationCidrBlock' in attrs.keys() and
                                   'InstanceId' in attrs.keys() and 
                                   attrs['DestinationCidrBlock'] == '0.0.0.0/0'
                                  ):
                                    r['expected_local'].append(rt)
    pprint(r)
    return r


def retrieve_tags(instance):
    tags = dict(map(
        lambda tag: ( tag['Key'], tag['Value'] ),
        instance.tags
    ))
    return tags

def log_prepare(level, logfile, size, retention):
    """
    instantiate a logger according the given parameters
    level, size, retention are self-explaining
    """
    logger = logging.getLogger()
    formatter = logging.Formatter('%(asctime)s :: [%(levelname)s] :: %(message)s')
    loglevel = logging.getLevelName(level)

    logger.setLevel(loglevel)
    logfile_handler = RotatingFileHandler(logfile, 'a', size, retention)
    logfile_handler.setLevel(loglevel)
    logfile_handler.setFormatter(formatter)
    logger.addHandler(logfile_handler)

    return logger

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: %s config.json" % sys.argv[0])
        sys.exit(1)

    with open(sys.argv[1], 'r') as f:
        config = json.load(f)

    logger = log_prepare(
        config['log']['log_level'],
        config['log']['logfile'],
        config['log']['max_log_size'] * 1024 * 1024,
        config['log']['retention']
    )
    logger.info("Creating the ec2 session...")

    # search for my peer
    local_id = requests.get("http://169.254.169.254/latest/meta-data/instance-id").text # name
    local_zone = requests.get("http://169.254.169.254/latest/meta-data/placement/availability-zone").text
    region = json.loads(requests.get("http://169.254.169.254/latest/dynamic/instance-identity/document").text)['region']
    
    sess = boto3.session.Session(
        region_name=region,
        profile_name=config['profile']
    )

    ec2_session = sess.resource('ec2')

    local_nat = ec2_session.Instance(local_id) # boto obj
    local_tags = retrieve_tags(local_nat)
    
    remote_nat = "not_defined"

    if config['pattern'] not in local_tags[config['tag']]:
        logger.critical("The local instance doesn't carry the aws-nat roles, stop here")
        print("The nat should have a aws-nat roles. Fix your tags/deploy")
        sys.exit(1)

    for i in ec2_session.instances.all():
        if config['pattern'] in retrieve_tags(i)[config['tag']] and i.id != local_nat.id:
            print("%s is a good peer candidate" % i.id)
            remote_nat = ec2_session.Instance(i.id)
            break
    
    if remote_nat is "not_defined":
        logger.critical("No peer found (ie. no other instance with aws-nat role), stop here")
        sys.exit(2)
    
    vpc = ec2_session.Vpc(local_nat.vpc_id)
    routes = update_route_dict(vpc)

    remote_nat_ip = remote_nat.private_ip_address
    local_nat_ip = local_nat.private_ip_address
    logger.info("remote nat: %s  --- local nat: %s" % (local_nat_ip, remote_nat_ip))
    print("remote nat: %s  --- local nat: %s" % (local_nat_ip, remote_nat_ip))

    logger.info("Hi friends ! I'm a NAT instance ! Let's get to work !")
    switch_routes(routes['expected_local'], local_nat, logger, ec2_session)
    routes = update_route_dict(vpc)

    logger.info("Spawning the monitoring thread")

    ping = PingLoop(remote_nat_ip, config['ping'], logger, routes['remote'], ec2_session, local_nat)
    try:
        ping.ping_loop()
    except:
        logger.critical("Exception caught")
    finally:
        logger.info("Shutting everything down")
        for procs in multiprocessing.active_children():
            logger.info("shutting down: %r", procs)
            procs.terminate()
            procs.join()
        logger.info("done.")
