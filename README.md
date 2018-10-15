# Nat Monytor

Essentially a rewrite from the code here : 

https://aws.amazon.com/articles/high-availability-for-amazon-vpc-nat-instances-an-example/

We needed big changes in order to avoid using : 

- amazon-tuned centos AMIs (and the API helpers)
- chunks of messy shell scripts
- centralized and maintainable configuration

## Usage

The script rely on requests and boto3. Python 3.6 was used for writing and testing

```
pip install -r requirements.txt
python3 monyt.py config_monyt.json
```

The configuration is done through the json file.

## How

The script ping its peer, if it detects it down it will modify the route tables, and attempt to stop/start the other
nat-instance.
