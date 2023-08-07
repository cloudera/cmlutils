# **cmlutil** 

`cmlutil` is a command-line interface (CLI) tool designed to enhance the [Cloudera Machine Learning (CML)](https://docs.cloudera.com/machine-learning/cloud/index.html) experience. It provides various utilities and functionalities to help working with Cloudera Machine Learning.

`cmlutil project` command helps to migrate a CDSW/CML [projects](https://docs.cloudera.com/machine-learning/cloud/projects/index.html)
(along with associated assets like [models](https://docs.cloudera.com/machine-learning/cloud/models/index.html),
[jobs](https://docs.cloudera.com/machine-learning/cloud/jobs-pipelines/index.html) and [applications](https://docs.cloudera.com/machine-learning/cloud/applications/index.html))
to another CML workspace. This tool aims to solve for migrating projects from legacy CDSW clusters (which will be EOL'd soon)
to CML public cloud/private cloud. The tool uses the host it is running on as its "scratch space" for temporarily holding project
data and metadata before the project is fully migrated to the target CML workspace. This host is interchangeably referred to as "Bastion host" or "local machine" in this document.
## CML Project migration documentation
The comprehensive documentation for project migration can be located within the [GitHub wiki page](https://github.com/cloudera/cmlutils/wiki).
## Installation

### Development mode
1. Clone the repo and run `python3 -m pip install --editable .` .
2. Check if the command `cmlutil` is running or not.
3. By installing the CLI in editable mode, any changes done to the source code would reflect in real-time without the need for re-installing again.

### For production
1. To install from `main` branch:
```
python3 -m pip install git+https://github.com/cloudera/cmlutils@main
```
2. Or from a feature or release branch:
```
python3 -m pip install git+https://github.com/cloudera/cmlutils@<branch-name>
```
## Development Guidelines
* We use two formatting tools, namely `black` and `isort` to format our python repo. Please run these commands before commiting any changes. `isort` helps arranging the imports in a logical manner.
  * They can be installed using `python3 -m pip install black isort`.
  * Run `black .` while inside the root directory.
  * Run `isort --profile black .`.

## Reporting bugs and vulnerabilities

 - To report a vulnerability, please email security@cloudera.com . For more information, visit https://www.cloudera.com/contact-us/security.html .
 - To report a bug, please do it in "GitHub Issues".

## Supplemental Disclaimer
Please read the following before proceeding.

Cloudera, Inc. (“Cloudera”) makes the cmlutil available as an open source tool for the convenience of its users.  Although Cloudera expects that the tool will help users working with Cloudera Machine Learning, Cloudera makes cmlutil available “as is” and without any warranty or support.  By downloading and using cmlutil, you acknowledge the foregoing statement and agree that Cloudera is not responsible or liable in any way for your use of cmlutil.