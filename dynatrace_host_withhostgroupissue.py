#
# Made by Guillaume HENON
# October 2023
#
import logging,traceback,argparse, configparser
import jinja2
from logging import raiseExceptions
import os,datetime
import requests
import json
import re
from datetime import datetime

BASE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)) + os.sep)
BASE_DATA_DIR = BASE_DIR + 'data'+ os.sep
REUSE=False

ap = argparse.ArgumentParser(description="Script to check hosts with badly formatting hostgroup")
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
STRINGSTOCHECK=config['DYNATRACE']['HOSTGROUP_CHECKSTRINGINNAME'].upper().split(',')
STRINGSTOCHECKMISSING=config['DYNATRACE']['HOSTGROUP_CHECKSTRINGNOTINNAME'].upper().split(',')


#https://docs.dynatrace.com/docs/dynatrace-api/environment-api/topology-and-smartscape/hosts-api/get-all

def checkinhostgroupname(v_hostgroupname):
    v_hostgroupname=v_hostgroupname.upper()
    for s in range(len(STRINGSTOCHECK)):
        if not STRINGSTOCHECK[s] in v_hostgroupname:
            return True
    return False
    
def checknotinhostgroupname(v_hostgroupname):
    v_hostgroupname=v_hostgroupname.upper()
    if STRINGSTOCHECKMISSING[0]:
        for s in range(len(STRINGSTOCHECKMISSING)):
            if STRINGSTOCHECKMISSING[s] in v_hostgroupname:
                return True
    return False

def list_monitored_host():
    problemList=[]
    base_url=DYNATRACE_URL+"/api/v2/entities?pageSize=3000&entitySelector=type%28%22HOST%22%29&from=now-10d&to=now&fields=tags,properties.STATE,properties.MONITORINGMODE,properties.HOSTGROUPNAME"
    #base_url=DYNATRACE_URL+"/api/v2/entities?pageSize=3000&entitySelector=type%28%22HOST%22%29&from=now-10d&to=now&fields=tags,agentVersion,discoveredName,displayName,ipAddresses,localHostName,localIp,monitoringMode,oneAgentCustomHostName"
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

d_hosts=list_monitored_host()
logging.info("Hosts in Dynatrace: "+ str(len(d_hosts)))
logging.debug(d_hosts)

nbwarning=0
len_servers=len(d_hosts)
l_badhostgroup=[]
for s in range(len_servers):
    l_badhostgroup.append(d_hosts[s])
        
l_sorted_list = sorted(l_badhostgroup, key=lambda x: x['displayName'])
logging.debug(l_sorted_list)

#build list with needed information
l_webpage=[]
l_webpage.append(["#","Name","HostGroup","Comments"])

l_hostgroupchecktag=config['DYNATRACE']['HOSTGROUP_CHECKTAG'].split(',')
l_valuetoheck="None"
l_keytocheck="None"
if l_hostgroupchecktag[0]:
    l_keytocheck=l_hostgroupchecktag[0]
if len(l_hostgroupchecktag)>1:
    l_valuetoheck=l_hostgroupchecktag[1]
logging.info('check tag: key['+l_hostgroupchecktag[0]+'] value['+l_valuetoheck+']')


for l in range(len(l_sorted_list)):
    #l_webpage.append([str(l),l_sorted_list[l]['name'],l_sorted_list[l]['sys_id']])
    l_tags=l_sorted_list[l]['tags']
    l_properties=l_sorted_list[l]['properties']
    l_comments=None
    l_hostgroupname=None
    # make check only on running hosts
    #if not any(d['main_color'] == 'red' for d in a):
    if l_properties.get('state')=="RUNNING" and "monitoringMode" in l_properties:
        if not "hostGroupName" in l_properties:
            l_comments="Missing Host Group"
            nbwarning=nbwarning+1
        else:
        #if any(key in d for d in dict_list):
        #if not any(d.get('main_color', default_value) == 'red' for d in a):
            l_keyexists=False
            l_hostgroupname=l_sorted_list[l]['properties']['hostGroupName']
            if checkinhostgroupname(l_hostgroupname):
                l_comments="At least one expected string in hostgroup name not found"
                nbwarning=nbwarning+1
            else:
                if checknotinhostgroupname(l_hostgroupname):
                    l_comments="At least one NOT expected string found in hostgroup name"
                    nbwarning=nbwarning+1
                else:
                    for t in range(len(l_tags)):
                        #if "\'key\': \'PROD_ENV\', \'value\': \'Unknown\'" in l_tags:
                        if l_tags[t]['key']==l_keytocheck and not l_keytocheck=="None":
                            l_keyexists=True
                            if l_tags[t]['value']==l_valuetoheck and not l_valuetoheck=="None":
                                l_comments="Found key["+l_keytocheck+"] value["+l_valuetoheck+"] in tags"                      
                                nbwarning=nbwarning+1
                    if not l_keyexists and not l_keytocheck=="None":
                        l_comments="Missing key["+l_keytocheck+"] in tags"
                        nbwarning=nbwarning+1
     
    if l_comments:
        l_webpage.append([str(nbwarning),"<a href="+DYNATRACE_URL+"/ui/entity/"+l_sorted_list[l]['entityId']+" target=\"_blank\" rel=\"noopener noreferrer\">"+l_sorted_list[l]['displayName']+"</a>",l_hostgroupname,l_comments])
logging.debug(l_webpage)
logging.info("hosts with bad hostgroup: "+str(nbwarning))

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
<h2 align=center>Hosts with bad hostgroup name</h1>
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
            <td class="{{'red' if cell == "ERROR"}}">{{cell}}</td>
        {% endfor %}
    {% endif %}
</tr>
{% endfor %}
</table>
""")

template.globals['now'] = datetime.now
data={'attrs': l_webpage}
output_from_parsed_template=template.render(data)
with open(BASE_DIR+"www"+os.sep+ "HostBadHostGroup.html", "w") as fh:
    fh.write(output_from_parsed_template)

logging.info("End")
