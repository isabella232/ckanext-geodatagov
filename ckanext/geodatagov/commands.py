import collections
import os
import sys
import re
import csv
import json
import urllib
import lxml.etree
import ckan
import ckan.model as model
import ckan.logic as logic
import ckan.lib.cli as cli
import requests
import ckanext.harvest.model as harvest_model
import xml.etree.ElementTree as ET
import ckan.lib.munge as munge


import logging
log = logging.getLogger()



class GeoGovCommand(cli.CkanCommand):
    '''
    Commands:

        paster ecportal import-harvest-source <harvest_source_data> <user_to_org_data> -c <config>
        paster ecportal import-orgs <data> -c <config>
    '''
    summary = __doc__.split('\n')[0]
    usage = __doc__

    def command(self):
        '''
        Parse command line arguments and call appropriate method.
        '''
        if not self.args or self.args[0] in ['--help', '-h', 'help']:
            print GeoGovCommand.__doc__
            return

        cmd = self.args[0]
        self._load_config()

        user = logic.get_action('get_site_user')(
            {'model': model, 'ignore_auth': True}, {}
        )
        self.user_name = user['name']

        if cmd == 'import-harvest-source':
            if not len(self.args) in [3]:
                print GeoGovCommand.__doc__
                return

            self.import_harvest_source(self.args[1], self.args[2])

        if cmd == 'import-orgs':
            if not len(self.args) in [2, 3]:
                print GeoGovCommand.__doc__
                return

            self.import_organizations(self.args[1])


    def get_user_org_mapping(self, location):
        user_org_mapping = open(location)
        fields = ['user', 'org']
        csv_reader = csv.reader(user_org_mapping)
        mapping = {}
        for row in csv_reader:
            mapping[row[0].lower()] = row[1]
        return mapping


    def import_harvest_source(self, sources_location, user_org_mapping):
        '''Import data from this mysql command
select DOCUUID, TITLE, OWNER, APPROVALSTATUS, HOST_URL, Protocol, PROTOCOL_TYPE, FREQUENCY, USERNAME into outfile '/tmp/results_with_user.csv' from GPT_RESOURCE join GPT_USER on owner = USERID where frequency is not null;
'''
        mapping = self.get_user_org_mapping(user_org_mapping)

        fields = ['DOCUUID', 'TITLE', 'OWNER', 'APPROVALSTATUS', 'HOST_URL',
        'PROTOCAL', 'PROTOCOL_TYPE', 'FREQUENCY', 'USERNAME']

        user = logic.get_action('get_site_user')({'model': model, 'ignore_auth': True}, {})

        harvest_sources = open(sources_location)
        try:
            csv_reader = csv.reader(harvest_sources, delimiter='\t')
            for row in csv_reader:
                row = dict(zip(fields,row))

                ## neeeds some fix
                if row['PROTOCOL_TYPE'].lower() not in ('waf', 'csw', 'z3950'):
                    continue

                frequency = row['FREQUENCY'].upper()
                if frequency not in ('WEEKLY', 'MONTHLY', 'BIWEEKLY'):
                    frequency = 'MANUAL'

                config = {
                          'APPROVALSTATUS': row['APPROVALSTATUS'],
                          'ORIGINAL_UUID': row['DOCUUID'][1:-1].lower()
                         }

                root = ET.fromstring(row['PROTOCAL'])

                for child in root:
                    if child.text:
                        config[child.tag] = child.text

                harvest_source_dict = {
                    'name': munge.munge_title_to_name(row['TITLE']),
                    'title': row['TITLE'],
                    'url': row['HOST_URL'],
                    'source_type': row['PROTOCOL_TYPE'].lower(),
                    'frequency': frequency,
                    'config': json.dumps(config),
                    'owner_org': mapping[row['USERNAME'].lower()]
                }


                try:
                    harvest_source = logic.get_action('harvest_source_create')(
                        {'model': model, 'user': user['name'],
                         'session': model.Session, 'api_version': 3},
                        harvest_source_dict
                    )
                except ckan.logic.ValidationError, e:
                    print harvest_source_dict
                    print e.error_dict

        finally:
            model.Session.commit()
            harvest_sources.close()

    def import_organizations(self, location):
        fields = ['title', 'type', 'name']

        user = logic.get_action('get_site_user')({'model': model, 'ignore_auth': True}, {})
        organizations = open(location)

        csv_reader = csv.reader(organizations)

        all_rows = set()
        for row in csv_reader:
            all_rows.add(tuple(row))

        for num, row in enumerate(all_rows):
            row = dict(zip(fields,row))
            org = logic.get_action('organization_create')(
                {'model': model, 'user': user['name'],
                 'session': model.Session},
                {'name': row['name'],
                 'title': row['title'],
                 'extras': [{'key': 'organization_type',
                             'value': json.dumps(row['type'])}]
                }
            )
