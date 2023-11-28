#
# Made by Guillaume HENON
# October 2023
#
import logging,traceback,argparse, configparser
import jinja2
from logging import raiseExceptions
import os,datetime
from utils import dynatrace_utils

BASE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)) + os.sep)
BASE_DATA_DIR = BASE_DIR + 'data'+ os.sep
REUSE=False

ap = argparse.ArgumentParser(description="Script to compare servers in ServiceNow CMDB and host in Dynatrace through an API call")
# Add the arguments to the parser
ap.add_argument("-d", "--debug", action="store_true",help="Set debug mode")
args = ap.parse_args()

isdebug=args.debug
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
SERVICENOW_URL=config['SERVICENOW']['URL']
query=config['SERVICENOW']['SERVERSTOMONITOR_QUERY']

import requests
import json
import re

from datetime import datetime

#query="sys_class_name=cmdb_ci_win_server^ORsys_class_name=cmdb_ci_linux_server^u_status=Deployed^monitor=True^u_sub_status=Functional^location!=4c48ab534f719200789de3518110c7d2^supported_by!=6935d826db8d178cef5892b8db9619e6^location!=2848ab534f719200789de3518110c7e2"

def list_deployed_server():
    oneinc=""
     
    url = SERVICENOW_URL+"/api/now/cmdb/instance/cmdb_ci_server?sysparm_query="+query+"&sysparm_limit=3000&sysparm_view=Desktop&sysparm_display_value=true"
    user = config['SERVICENOW']['API_USER']
    password = config['SERVICENOW']['API_PASSWD']
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    datafile=BASE_DATA_DIR+'servicenow_list_deployed_server.json'
    try:
        if REUSE and os.path.isfile(datafile) :
            with open(datafile) as f:
                json_data=json.load(f)
        else:
            logging.info("Query ServiceNow: find servers, using URL["+url+"]")
            response = requests.get(url, auth=(user, password), headers=headers)
            response.raise_for_status()
            logging.debug("ServiceNow Query Servers API response: "+str(response.status_code))
            json_data = response.json()
            with open(datafile, 'w', encoding='utf-8') as f:
                json.dump(json_data, f, ensure_ascii=False, indent=4)
            o_serverlist=""
        if "result" in json_data:
            o_serverlist=json_data['result']      

    except Exception as err:
        logging.error(err)
        logging.error(traceback.format_exc())
    return o_serverlist

def list_monitored_host():
    problemList=[]
    base_url=DYNATRACE_URL+"/api/v2/entities?pageSize=3000&entitySelector=type%28%22HOST%22%29&from=now-10d&to=now&fields=properties.STATE"
    #base_url=DYNATRACE_URL+"/api/v2/entities?pageSize=3000&entitySelector=type%28%22HOST%22%29,&from=now-10d&to=now"
    datafile=BASE_DATA_DIR+'dynatrace_activehosts.json'
    token=config['DYNATRACE']['TOKEN_READ_ENTITY']
    session = requests.Session()
    session.headers.update({"Accept":"application/json"})
    session.headers.update({"Content-Type":"application/json"})
    session.headers.update({"Authorization": "Api-Token "+token})
    try:
        if REUSE and os.path.isfile(datafile) :
            with open(datafile) as f:
                json_data=json.load(f)
        else:
            response = session.get(base_url)
            response.raise_for_status()
            logging.debug("Dynatrace list host API response: "+str(response.status_code))
       #     text = json.dumps(response.json(), sort_keys=True, indent=4)
            json_data = response.json()
            with open(datafile, 'w', encoding='utf-8') as f:
                json.dump(json_data, f, ensure_ascii=False, indent=4)

        hostscount=json_data['totalCount']
        logging.info("Hosts count:"+str(hostscount))
        o_hostlist=json_data['entities']
        for i in range(len(o_hostlist)):
            o_hostlist[i]['shortName']=o_hostlist[i]['displayName'].split('.')[0]
    except Exception as err:
        logging.error(err)
        logging.error(traceback.format_exc())
    return o_hostlist
    
logging.info("Start")
logging.info("Retrieve Servers")

d_servers=list_deployed_server()
logging.info("Servers in ServiceNow CMDB: "+ str(len(d_servers)))
logging.debug(d_servers)

d_hosts=list_monitored_host()
logging.info("Hosts in Dynatrace: "+ str(len(d_hosts)))
logging.debug(d_hosts)

# Check if each server in cmdb is monitored

nbwarning=0
len_servers=len(d_servers)
l_notmonitored=[]
for s in range(len_servers):
    oneserver=d_servers[s]['name']
#    if oneserver in d_hosts:
    
    if any(dictionary.get('shortName').upper() == oneserver.upper() for dictionary in d_hosts):
        logging.info('Server['+oneserver+'] is monitored')
    else:
        logging.warning('Server['+oneserver+'] is NOT monitored')
        l_notmonitored.append(d_servers[s])
        nbwarning=nbwarning+1
        
logging.info('Servers not monitored:'+str(nbwarning))
l_sorted_list = sorted(l_notmonitored, key=lambda x: x['name'])
logging.info(l_sorted_list)
logging.info("Send Metric")
dynatrace_utils.send_metric("apps.web.dynatrace.hostnotmonitored",nbwarning)
logging.info("Create Web page")
#build list with needed information
l_webpage=[]
l_webpage.append(["#","Name"])
for l in range(len(l_sorted_list)):
    #l_webpage.append([str(l),l_sorted_list[l]['name'],l_sorted_list[l]['sys_id']])
    l_webpage.append([str(l),"<a href="+SERVICENOW_URL+"/nav_to.do?uri=%2Fcmdb_ci_server.do%3Fsys_id%3D"+l_sorted_list[l]['sys_id']+" target=\"_blank\" rel=\"noopener noreferrer\">"+l_sorted_list[l]['name']+"</a>"])
scope_url=SERVICENOW_URL+"/nav_to.do?uri=%2Fcmdb_ci_server_list.do%3Fsysparm_query="+query
logging.info("ServiceNow scope URL["+scope_url+"]")  
logging.debug(l_webpage)


template= jinja2.Template("""
<html>
<title>Dynatrace - ServiceNow sanity check</title>
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
<h1 align=center><b>Dynatrace - ServiceNow Sanity Check</b></h1>
<h2 align=center>Deployed servers not monitored</h1>
<p>Last Update at {{ now() }}</p>
<p>Scope Analyzed is {{ scope_url }}</p>
<p>Servers not monitored: {{ nbhostnotmonitored }}</p>
<table>
{% for row in attrs %}
<tr>
    {% if loop.index == 1 %}
        {% for cell in row %}
            <th>{{cell}}</th>
        {% endfor %}
    {% else %}
        {% for cell in row %}
            <td class="{{'red' if cell == "ERROR"}}">{{cell}}</td>
        {% endfor %}
    {% endif %}
</tr>
{% endfor %}
</table>
""")

template.globals['now'] = datetime.now
html_scope_url="<a href="+scope_url+" target=\"_blank\" rel=\"noopener noreferrer\">"+scope_url+"</a>"
data={'attrs': l_webpage,'scope_url': html_scope_url,'nbhostnotmonitored': str(nbwarning)}
output_from_parsed_template=template.render(data)
with open(BASE_DIR+"www"+os.sep+ "HostNotMonitored.html", "w") as fh:
    fh.write(output_from_parsed_template)

logging.info("End")
