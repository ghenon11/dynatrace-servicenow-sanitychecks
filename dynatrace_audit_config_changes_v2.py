import logging,traceback,argparse, configparser
import jinja2
from logging import raiseExceptions
import os,datetime,math,glob
import requests
import json
from datetime import datetime

BASE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)) + os.sep)
BASE_DATA_DIR = BASE_DIR + 'data'+ os.sep

ap = argparse.ArgumentParser(description="Script to list configuration changes in Dynatrace through an API call")
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




# https://stackoverflow.com/questions/52559412/search-nested-json-dict-for-multiple-key-values-matching-specified-keys

def isnot_special_characters(character):
    #especially removing \ and formatting
    if character.isalnum() or character in [' ','!', '"', '#', '$', '%', '&', '(', ')', '*', '+', ',', '-', '.', '/', ':', ';', '<', '=', '>', '?', '@', '[',']', '^', '_', '`', '{', '|', '}', '~']:
        return True
    else:
        return False
    
def cleanup():
    try:
        for filename in glob.glob(BASE_DATA_DIR+"dynatrace_auditlogs_*"):
            logging.info('Removing '+filename)
            os.remove(filename) 
    except Exception as err:
        logging.error(err)
        print(traceback.format_exc())

def download_audit_logs():
    datafile=BASE_DATA_DIR+'dynatrace_auditlogs.json'
    try:
        json_data=download_audit_logs_page("")
        with open(datafile, 'w', encoding='utf-8') as f:
            json.dump(json_data, f, ensure_ascii=False, indent=4)
        auditlogs=json_data['auditLogs']
        c_nbpage=math.ceil(json_data['totalCount']/json_data['pageSize'])
        c_page=1
        while 'nextPageKey' in json_data:
            c_page=c_page+1
            logging.info("Progress["+str(c_page)+"/"+str(c_nbpage)+"]")
            json_data=download_audit_logs_page(json_data['nextPageKey'])
            with open(datafile, 'a', encoding='utf-8') as fa:
                json.dump(json_data, fa, ensure_ascii=False, indent=4)
            auditlogs=auditlogs+json_data['auditLogs']            
    except Exception as err:
        logging.error(err)
        print(traceback.format_exc())
    return auditlogs


def download_audit_logs_page(f_page):
    if f_page:
        base_url=DYNATRACE_URL+"/api/v2/auditlogs?nextPageKey="+f_page
    else:
        #base_url=DYNATRACE_URL+"/api/v2/auditlogs?pageSize=200&filter=category(CONFIG)&from=now-2w"
        base_url=DYNATRACE_URL+"/api/v2/auditlogs?pageSize=200&filter=category(CONFIG)"
    datafile=BASE_DATA_DIR+"dynatrace_auditlogs_"+f_page+".json"
    token=config['DYNATRACE']['TOKEN_READ_AUDITLOGS']
    logging.info('Retrieve Page['+f_page+']')
    session = requests.Session()
    session.headers.update({"Accept":"application/json"})
    session.headers.update({"Content-Type":"application/json"})
    session.headers.update({"Authorization": "Api-Token "+token})
    try:
        response = session.get(base_url)
        response.raise_for_status()
        logging.debug("Auditlogs API response: "+str(response.status_code))
        auditlogspage = response.json()
        with open(datafile, 'w', encoding='utf-8') as f:
            json.dump(auditlogspage, f, ensure_ascii=False, indent=4)
                    
    except Exception as err:
        logging.error(err)
        print(traceback.format_exc())
    return auditlogspage

logging.info("Start")
logging.info("Retrieve Configuration changes")

d_auditlogs=download_audit_logs()
logging.info("Auditlogs records: "+ str(len(d_auditlogs)))
logging.debug(d_auditlogs)

l_webpage=[]
l_webpage.append(["timestamp","entityId","eventType","user","operation","path","newvalue","oldvalue"])
smatch_entity=[]
for i in config['DYNATRACE']['AUDITLOGS_ENTITIES_TO_EXCLUDE'].split(','): 
    smatch_entity.append(i)
logging.debug(smatch_entity)

smatch_user=[]
for i in config['DYNATRACE']['AUDITLOGS_USER_TO_EXCLUDE'].split(','): 
    smatch_user.append(i)
logging.debug(smatch_user)

#smatch_user=['settings conversion migration','system','ExtensionAsyncRequestsWorker','settings notification handler','runtime configuration migration','notificationHandler']
    
for l in range(len(d_auditlogs)):
    #smatch_entity=['DASHBOARDS_SETTINGS','DATA_EXPLORER','alerting.maintenance-window']
    l_entityId=d_auditlogs[l]['entityId']
    l_user=d_auditlogs[l]['user']
    if not any(ext in l_entityId for ext in smatch_entity) and not any(ext2 in l_user for ext2 in smatch_user):
        l_time=datetime.fromtimestamp(int(d_auditlogs[l]['timestamp'])/1000).strftime("%Y-%m-%d %H:%M:%S")
        for p in range(len(d_auditlogs[l]['patch'])):
            l_value=""
            if 'value' in d_auditlogs[l]['patch'][p]:
                if not str(d_auditlogs[l]['patch'][p]['value'])=="None":
                #l_value=d_auditlogs[l]['patch'][p]['value']
                    l_value=''.join(filter(isnot_special_characters,str(d_auditlogs[l]['patch'][p]['value']) ))
            else:
                l_value=""
            l_oldValue=""
            if 'oldValue' in d_auditlogs[l]['patch'][p]:
                if not str(d_auditlogs[l]['patch'][p]['oldValue'])=="None":
                    l_oldValue=''.join(filter(isnot_special_characters,str(d_auditlogs[l]['patch'][p]['oldValue']) ))
            #keep only first 500 characters
            l_value=str(l_value)[:500]           
            l_oldValue = str(l_oldValue)[:500]
            l_webpage.append([l_time,d_auditlogs[l]['entityId'],d_auditlogs[l]['eventType'],d_auditlogs[l]['user'],d_auditlogs[l]['patch'][p]['op'],d_auditlogs[l]['patch'][p]['path'],l_value,l_oldValue])

logging.debug(l_webpage)
logging.info("Record kept["+str(len(l_webpage))+"]")

template= jinja2.Template("""
<html>
<title>Dynatrace - Audit Configuration changes</title>
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
<h1 align=center><b>Dynatrace - Audit Configuration changes</b></h1>
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
try:
    output_from_parsed_template=template.render({'attrs': l_webpage})
    with open(BASE_DIR+"www"+os.sep+"AuditConfigChanges.html", "w") as fh:
        fh.write(output_from_parsed_template)
except Exception as err:
    logging.error(err)
    print(traceback.format_exc())

logging.info("Cleanup")
cleanup()
logging.info("End")