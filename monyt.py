import boto3
import requests
import json
import logging
import sys
from logging.handlers import RotatingFileHandler 
import time

import multiprocessing
from subprocess import Popen, PIPE, STDOUT


class PingLoop(object):
    def __init__(self, host, param, logger):
        self.logger = logger
        self.host = host
        self.param = param

    def ping_loop(self):
        while True:
            self.logger.info("waiting for next ping... %ds", self.param['nextping'])
            time.sleep(self.param['nextping'])

            p = Popen(["ping", "-c", str(self.param['num']), 
                    "-W", str(self.param['timeout']), self.host], 
                    stdout=PIPE, stderr=STDOUT)
            if p.wait() != 0:
                self.logger.critical("Failed to ping.")
                out, err = p.communicate()
                self.logger.info(out)
                # call the failover func
            else:
                self.logger.info("Successfull ping : %s, count=%s, timeout=%s" % 
                             (self.host, self.param['num'], self.param['timeout'])
                            )

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: %s config.json" % sys.argv[0])
        sys.exit(1)

    with open(sys.argv[1], 'r') as f:
        config = json.load(f)

    logger = logging.getLogger()
    formatter = logging.Formatter('%(asctime)s :: [%(levelname)s] :: %(message)s')

    loglevel = logging.getLevelName(config['log']['log_level'])
    logfile = config['log']['logfile']
    size = config['log']['max_log_size'] * 1024 * 1024
    retention = config['log']['retention']

    logger.setLevel(loglevel)
    logfile_handler = RotatingFileHandler(logfile, 'a', size, retention)
    logfile_handler.setLevel(loglevel)
    logfile_handler.setFormatter(formatter)
    logger.addHandler(logfile_handler)
    logger.info("Creating the ec2 session...")

    sess = boto3.session.Session(
        region_name=config['aws']['region'],
        profile_name=config['aws']['profile']
    )

    ec2_session = sess.resource('ec2')

    remote_nat = ec2_session.Instance(config['nat_peer'])
    local_nat = ec2_session.Instance(config['local_peer'])

    remote_nat_ip = remote_nat.private_ip_address
    local_nat_ip = local_nat.private_ip_address
    logger.info("remote nat: %s  --- local nat: %s" % (local_nat_ip, remote_nat_ip))
    logger.info("Spawning the monitoring thread")

    ping = PingLoop("127.0.0.1", config['ping'], logger)

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

