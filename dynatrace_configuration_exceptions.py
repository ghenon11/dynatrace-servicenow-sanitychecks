#
# Made by Guillaume HENON
# October 2023
#
import logging,traceback,argparse, configparser
from logging import raiseExceptions
import os,datetime
import json,jinja2
#pip install pyyaml
import yaml
import re
from datetime import datetime
from dynatrace import Dynatrace
import pathlib

BASE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)) + os.sep)
BASE_DATA_DIR = BASE_DIR + 'data'+ os.sep
REUSE=False

ap = argparse.ArgumentParser(description="Script to compare open problems in Dynatrace and incidents in ServiceNow through API calls")
# Add the arguments to the parser
ap.add_argument("-d", "--debug", action="store_true",help="Set debug mode")
ap.add_argument("monaco_path",help="Path of the Monaco export")
args = ap.parse_args()

isdebug=args.debug
monaco_path=args.monaco_path
# C:\Users\10023266\OneDrive - bioMerieux\ISOPS Core\dynatrace\Monaco\dynatrace-monaco\project_production


loglevel=logging.INFO
if isdebug:
    loglevel=logging.DEBUG

try:
    logname,ext=os.path.splitext(BASE_DIR+os.path.basename(__file__))
    logname=logname+".log"
    logging.basicConfig(format='%(asctime)s::%(levelname)s::%(message)s', filename=logname, filemode="w", level=loglevel)
except:
    logging.error("error when defining logging")
    
configfile="dynatrace_sanity_checks.ini"
if os.path.isfile(configfile):
    config = configparser.ConfigParser()
    config.read(configfile)
else:
    logging.error("Config file ["+configfile+"] is missing")
    exit()
    
logging.debug(config.sections())
logging.debug(config['DYNATRACE']['URL'])
DYNATRACE_URL=config['DYNATRACE']['URL']
TOKEN=config['DYNATRACE']['TOKEN_READ_ENTITY']


def download_host_list(v_dt):
    try:
        return v_dt.entities.list('type("HOST")', fields="properties.monitoringMode")
                   
    except Exception as err:
        logging.error(err)
        logging.error(traceback.format_exc())
        exit()
    return True

def download_hostgroup_list(v_dt):
    try:
        return v_dt.entities.list('type("HOST_GROUP")')
                   
    except Exception as err:
        logging.error(err)
        logging.error(traceback.format_exc())
        exit()
    return True

def analyze_file(v_filename):
    try:
        logging.debug(v_filename)
        if os.path.isfile(v_filename):
            with open(v_filename, "r") as file:
                configs = yaml.load(file, Loader=yaml.FullLoader)
        else:
            logging.error("bad file: "+v_filename)
            exit()
        
                
    except Exception as err:
        logging.error(err)
        logging.error(traceback.format_exc())
        exit()
    return configs

logging.info("Start")
host_list=[]
hostgroup_list=[]
entiry_list=[]
exception_list=[]
configs_list=[]
dt = Dynatrace(DYNATRACE_URL,TOKEN)
host_list=download_host_list(dt)
hostgroup_list=download_hostgroup_list(dt)
entity_list=[y for x in [host_list, hostgroup_list] for y in x]
logging.info("Host and hostgroup exported")

#The list is created by placing elements in [ ] separated by commas “,”	The dictionary is created by placing elements in { } as “key”:”value”, each key-value pair is separated by commas “, “
{'configs': [{'id': '0c599652-a603-360d-8b75-26f9d5d17b34', 'config': {'template': '0c599652-a603-360d-8b75-26f9d5d17b34.json', 'skip': False, 'originObjectId': 'vu9U3hXa3q0AAAABACRidWlsdGluOmFub21hbHktZGV0ZWN0aW9uLmRpc2stcnVsZXMABnRlbmFudAAGdGVuYW50ACQxODllNDM3Ni04MDZmLTNiNDctOWIyNC1hYjQ0NTkxYTYxNjO-71TeFdrerQ'}, 'type': {'settings': {'schema': 'builtin:anomaly-detection.disk-rules', 'schemaVersion': '1.0.3', 'scope': 'environment'}}}, {'id': 'd3ad27d7-f049-3471-b00f-8fc1c4b508c8', 'config': {'template': 'd3ad27d7-f049-3471-b00f-8fc1c4b508c8.json', 'skip': False, 'originObjectId': 'vu9U3hXa3q0AAAABACRidWlsdGluOmFub21hbHktZGV0ZWN0aW9uLmRpc2stcnVsZXMABnRlbmFudAAGdGVuYW50ACRmZjVhM2I1Mi1jMGNmLTMxYzMtYjVmOC0yOTcyN2QwY2FlMDO-71TeFdrerQ'}, 'type': {'settings': {'schema': 'builtin:anomaly-detection.disk-rules', 'schemaVersion': '1.0.3', 'scope': 'environment'}}}]}
for current_path, dirs, files in os.walk(monaco_path):
    for name in files:
        if "config.yaml" in name.lower() and "builtinanomaly-detection" in current_path.lower():
            filename=os.path.join(current_path,name)
            logging.info("Config file "+filename +" found")
            configs=analyze_file(filename)
            logging.debug(configs)
            configs_list=configs["configs"]
            for i in range(len(configs_list)):
                scope=configs_list[i]["type"]["settings"]["scope"]
                if "HOST-" in scope:
                    exception_list.append({"schema":configs_list[i]["type"]["settings"]["schema"],"type":"HOST","scope":scope,"name":"host_name"})
                if "HOST_GROUP-" in scope:
                    exception_list.append({"schema":configs_list[i]["type"]["settings"]["schema"],"type":"HOST_GROUP","scope":scope,"name":"hostgroup_name"})
 
logging.debug(str("Updated list"))   
logging.info("Searching names")
for i in range(len(exception_list)):
    entity_id=exception_list[i]["scope"]
    for l in range(len(entity_list)):
        if entity_id==entity_list[l].entity_id:
            exception_list[i]["name"]=entity_list[l].display_name

l_webpage=[]
l_webpage.append(["Schema","Type","ID","Name"])
for i in range(len(exception_list)):
    logging.debug(exception_list[i]["type"]+" "+exception_list[i]["name"]+" has a setting exception on "+exception_list[i]["schema"])               
    l_webpage.append([exception_list[i]["schema"],exception_list[i]["type"],exception_list[i]["scope"],exception_list[i]["name"]])
 
 
logging.info("Create Web page")
template= jinja2.Template("""
<html>
<title>Dynatrace sanity check</title>
<style type="text/css">
    table,th,td {
        border-collapse: collapse;
        border: 1px solid #8E8F3A
    }
    .red {
        color: red;
    }
    .yellow {
        color: yellow;
    }
    .green {
        color: green;
    }
</style>
<h1 align=center><b>Dynatrace Sanity Check</b></h1>
<h2 align=center>Hosts and host groups with specific settings</h1>
<p>Last Update at {{ now() }}</p>
<table>
{% for row in attrs %}
<tr>
    {% if loop.index == 1 %}
        {% for cell in row %}
            <th>{{cell}}</th>
        {% endfor %}
    {% else %}
        {% for cell in row %}
            <td>{{cell}}</td>
        {% endfor %}
    {% endif %}
</tr>
{% endfor %}
</table>
""")

template.globals['now'] = datetime.now
data={'attrs': l_webpage}
output_from_parsed_template=template.render(data)
with open(BASE_DIR+"www"+os.sep+ "SettingsExceptions.html", "w") as fh:
    fh.write(output_from_parsed_template)  
            
logging.info("End")

