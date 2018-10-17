# Nat Monytor

Essentially a rewrite from the code here : 

https://aws.amazon.com/articles/high-availability-for-amazon-vpc-nat-instances-an-example/

We needed big changes in order to avoid using : 

- amazon-tuned centos AMIs (and the API helpers)
- chunks of messy shell scripts
- centralized and maintainable configuration

## Usage

The script rely on **requests** and **boto3**. Python 3.6 was used for writing and testing

```
pip install -r requirements.txt
python3 monyt.py config_monyt.json
```

The configuration is done through the json file.

## How

The script ping its peer, if it detects it down it will modify the route tables

## For real ?

The program automagically search for instances which 'Name' tag matches '-nat-' (tag and pattern are configurable in 
the config_monyt.json file)

On your nat-instances, you will want to have the program launched upon startup. 

Either:

- Write an init script relevant to the system you are running (initV, rc, systemd, ...)
- add a line such as : `screen -d -m python3 /path/to/monyt.py /path/to/config.json` to `/etc/rc.local` (if you chose this option, the $PWD will be '/', the log will be found there by default (you can customize it in the json file))

## Todo

Document the policies needed in order to avoid setting the aws-access-key being over-privileged
