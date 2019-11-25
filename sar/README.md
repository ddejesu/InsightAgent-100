# sar
This agent collects data from sar and sends it to Insightfinder.
## Installing the Agent

### Short Version
```bash
bash <(curl https://raw.githubusercontent.com/insightfinder/InsightAgent/master/utils/fetch-agent.sh) sar && cd sar
vi config.ini
sudo ./install.sh --create # install on localhost
## or 
sudo ./install-remote.sh list_of_nodes # install on each of list_of_nodes
```

### Long Version
**Download the agent [tarball](https://github.com/insightfinder/InsightAgent/raw/master/sar/sar.tar.gz) and untar it:**
```bash
curl -L https://github.com/insightfinder/InsightAgent/raw/master/sar/sar.tar.gz -o sar.tar.gz
tar xvf sar.tar.gz && cd sar
```

**Copy `config.ini.template` to `config.ini` and edit it:**
```bash
cp config.ini.template config.ini
vi config.ini
```
See below for a further explanation of each variable.

#### Automated Install (local or remote)
**Review propsed changes from install:**
```bash
sudo ./install.sh
```

**Once satisfied, run:**
```bash
sudo ./install.sh --create
```

To deploy on multiple hosts, instead call 
```bash
sudo ./install-remote.sh list_of_nodes -f <nodelist_file>
```
Where `list_of_nodes` is a list of nodes that are configured in `~/.ssh/config` or otherwise reachable with `scp` and `ssh`.

#### Manual Install (local only)
**Check Python version & upgrade if using Python 3**
```bash
if [[ $(python -V 2>&1 | awk '{ print substr($NF, 1, 1) }') == "3" ]]; then \
2to3 -w getmetrics_sar.py; \
else echo "No upgrade needed"; fi
```

**Setup pip & required packages:**
```bash
sudo ./pip-config.sh
```

**Test the agent:**
```bash
python getmetrics_sar.py -t
```

**If satisfied with the output, configure the agent to run continuously:**
```bash
sudo ./cron-config.sh
```

### Config Variables
* `metrics`: Metrics to report to InsightFinder. Multiple `sar` flags have been grouped as below; see `man sar` for more information on each flag.
    * `os`: `-vw` (host level)
    * `mem`: `-Rr` (host level only)
    * `paging`: `-BSW` (host level only)
    * `io`: 
        * Host Level: `-bHq`
        * Device Level: `-y`
    * `network`: 
        * Device Level: `-n DEV -n EDEV`
        * Host Level: `-n NFS -n NFSD -n SOCK -n SOCK6 -n IP -n EIP -n ICMP -n EICMP -n TCP -n ETCP -n UDP -n IP6 -n EIP6 -n ICMP6 -n EICMP6 -n UDP6`
    * `filesystem`: `-dF` (device level)
    * `power`: `-m FAN -m IN -m TEMP -m USB` (device level)
    * `cpu`: `-m CPU -m FREQ -u ALL -P ALL` (per-core and host level)
* `exclude_devices`: Set to True to not report device-level data. Note that this will prevent CPU, power, filesystem, some I/O, and some network metrics from being reported. By default, device-level data is reported.
* `replay_days`: A comma-delimited list of days within the last fiscal month to replay (from `/var/log/sa/saDD`)
* `replay_sa_files`: A comma-delimited list of sa files or directories to replay.
* **`user_name`**: User name in InsightFinder
* **`license_key`**: License Key from your Account Profile in the InsightFinder UI. 
* `token`: Token from your Account Profile in the InsightFinder UI. 
* **`project_name`**: Name of the project created in the InsightFinder UI. 
* **`project_type`**: Type of the project - one of `metric, metricreplay, log, logreplay, incident, incidentreplay, alert, alertreplay, deployment, deploymentreplay`.
* **`sampling_interval`**: How frequently data is reported.
* **`run_interval`**: How frequently data is collected. Should match the interval used in cron.
* `chunk_size_kb`: Size of chunks (in KB) to send to InsightFinder. Default is `2048`.
* `if_url`: URL for InsightFinder. Default is `https://app.insightfinder.com`.
* `if_http_proxy`: HTTP proxy used to connect to InsightFinder.
* `if_https_proxy`: As above, but HTTPS.