# dynatrace-servicenow-sanitychecks
Set of python scripts that use Dynatrace and ServiceNow API to make sanity checks:
- open problems vs incidents
- monitoring vs CMDB
- check hostgroup names
- list changes in dynatrace settings

Also one to create a maintenance windows on a set of hosts immediately

Scripts will output results as html file in directory ./www
Scripts will put temporary files in directory ./data

Update the configuration file (.ini) with your settings

Use -h parameter for more information
Need request and jinga2 modules
