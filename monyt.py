import boto3
import requests
import json
import logging
import sys
from logging.handlers import RotatingFileHandler 
import time

import multiprocessing
from subprocess import check_output, CalledProcessError, Popen, PIPE, STDOUT

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
            if self.pause_heartbeat == 0:
                self.logger.info("waiting for next ping... %ds", self.param['nextping'])
                time.sleep(self.param['nextping'])

                command =["ping", "-c", str(self.param['num']), "-W", str(self.param['timeout']), self.host]

                p = Popen(command, stdout=PIPE, stderr=STDOUT)
                if p != 0:
                    self.logger.critical("Failed to ping: %s", p.communicate())
                    self.logger.info("Switching the remote route tables to here")
                    for route in self.routes:
                        logger.info("Treating route : %s", route.route_table_id)
                        r = self.ec2.Route(route.route_table_id, '0.0.0.0/0')
                        r.replace(InstanceId=self.local.id)
                    self.pause_heartbeat = 1
                    continue
                self.logger.info("Successfull ping : %s, count=%s, timeout=%s" % 
                            (self.host, self.param['num'], self.param['timeout']))
            else:
                self.logger.critical("The remote peer was down! Waiting 10' before I try to reach it again.")
                time.sleep(600)

def retrieve_tags(instance):
    tags = dict(map(
        lambda tag: ( tag['Key'], tag['Value'] ),
        instance.tags
    ))
    return tags

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

    sess = boto3.session.Session(
        region_name=config['aws']['region'],
        profile_name=config['aws']['profile']
    )

    ec2_session = sess.resource('ec2')

    # search for my peer
    #local_id = requests.get("http://169.254.169.254/latest/meta-data/instance-id").text # name
    local_id = "i-060254f836f88c2a8"
    local_nat = ec2_session.Instance(local_id) # boto obj
    local_tags = retrieve_tags(local_nat)
    remote_nat = "not_defined"

    if 'aws-nat' not in local_tags['nbs_roles']:
        logger.critical("The local instance doesn't carry the aws-nat roles, stop here")
        print("The nat should have a aws-nat roles. Fix your tags/deploy")
        sys.exit(1)

    for i in ec2_session.instances.all():
        if 'aws-nat' in retrieve_tags(i)['nbs_roles'] and i.id != local_nat.id:
            print("%s is a good peer candidate" % i.id)
            remote_nat = ec2_session.Instance(i.id)
            break
    
    if remote_nat is "not_defined":
        logger.critical("No peer found (ie. no other instance with aws-nat role), stop here")
        sys.exit(2)
    
    # finding the route tables pointing to our nat-instances 
    vpc = ec2_session.Vpc(local_nat.vpc_id)

    routes = {
        'local': [],
        'remote': []
    }

    for rt in vpc.route_tables.all():
        for attrs in rt.routes_attribute:
            if not ('DestinationCidrBlock' in attrs.keys() and 
                    'InstanceId' in attrs.keys()
                   ):
                continue
            if attrs['DestinationCidrBlock'] == '0.0.0.0/0':
                if attrs['InstanceId'] == local_nat.id:
                    routes['local'].append(rt)
                if attrs['InstanceId'] == remote_nat.id:
                    routes['remote'].append(rt)

    print("Found local route tables:")
    for l in routes['local']:
        print(" -", l.route_table_id )
    print("Found remote route tables:")
    for r in routes['remote']:
        print(" -", r.route_table_id)

    remote_nat_ip = remote_nat.private_ip_address
    local_nat_ip = local_nat.private_ip_address
    logger.info("remote nat: %s  --- local nat: %s" % (local_nat_ip, remote_nat_ip))
    print("remote nat: %s  --- local nat: %s" % (local_nat_ip, remote_nat_ip))
    logger.info("Spawning the monitoring thread")

    ping = PingLoop("12.12.12.12", config['ping'], logger, routes['remote'], ec2_session, local_nat)
    ping.ping_loop()
#    try:
#        ping.ping_loop()
#    except:
#        logger.critical("Exception caught")
#    finally:
#        logger.info("Shutting everything down")
#        for procs in multiprocessing.active_children():
#            logger.info("shutting down: %r", procs)
#            procs.terminate()
#            procs.join()
#        logger.info("done.")
