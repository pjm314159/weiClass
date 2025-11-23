import os
import configparser
config = configparser.ConfigParser()
config.read('config.ini')
os.environ["OPENID"] =config.get("user","openid")