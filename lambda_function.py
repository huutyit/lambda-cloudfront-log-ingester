import csv
import gzip
import json
from datetime import datetime

import boto3
from elasticsearch import Elasticsearch, RequestsHttpConnection
from elasticsearch import helpers

# Global vars
FIELDNAMES = (
    'logdate',  # this gets stripped and merged into a new timestamp field
    'logtime',  # this gets stripped and merged into a new timestamp field
    'edge-location',
    'src-bytes',
    'ip',
    'method',
    'host',
    'uri-stem',
    'status',
    'referer',
    'user-agent',
    'uri-query',
    'cookie',
    'edge-result-type',
    'edge-request-id',
    'host-header',
    'protocol',
    'resp-bytes',
    'time-taken'
    'forwarded-for',
    'ssl-protocol',
    'ssl-cipher',
    'edge-response-result-type'
)

def parse_log(filename):
    '''Parse the log file into a dict'''
    # init
    idx = 1
    recordset = []

    with gzip.open(filename) as data:

        result = csv.DictReader(data, fieldnames=FIELDNAMES, dialect="excel-tab")

        for row in result:
            # skip header rows - cruft
            if idx > 2:
                # cloudfront events are logged to the second only, date and time are seperate
                # fields which we remove and merge into a new timestamp field
                date = row.pop('logdate')
                row['timestamp'] = datetime.strptime(
                    date + " " + row.pop('logtime'), '%Y-%m-%d %H:%M:%S').isoformat()
                # add to new record dict
                record = {
                    "_index": "epilot-cloud-cloudfront-logs-" + date,
                    "_source": row
                }
                # append to recordset
                recordset.append(record)
            idx = idx + 1

    return recordset


def write_bulk(record_set, es_client, config):
    ''' Write the data set to ES, chunk size has been increased to improve performance '''
    print "Writing data to ES"
    resp = helpers.bulk(es_client,
                        record_set,
                        chunk_size=config['es_bulk_chunk_size'],
                        timeout=config['es_bulk_timeout'])
    return resp

def lambda_handler(event, context):
    '''Invoke Lambda '''
    # load config from json file in s3 bucket
    config = {
        'es_connection_timeout': 60,
        'es_bulk_timeout': '60s',
        'es_bulk_chunk_size': 1000, 
        'es_mapping': {
            'mappings': {
                'properties': {
                    'uri-stem': {
                        'type': 'keyword'
                    },
                    'ip': {
                        'type': 'keyword'
                    },
                    'host': {
                        'type': 'keyword'
                    },
                    'host-header': {
                        'type': 'keyword'
                    }
                }
            }
        }
    }

    # create ES connection with sts auth file
    es_client = Elasticsearch(
        cloud_id="test:dXMtZWFzdC0xLmF3cy5mb3VuZC5pbyQyMGM5ZGI5OWE5N2Q0NDIwYWI4MGEyMjYyODIzMTRiNCQxM2YwY2QyNzlhNDQ0ZmZkOTlhOWJkYzk3N2I5ODg0Ng==",
        http_auth=("elastic", "ViedHKndVkSZQmSZFCy7FKOy")
    )

    # create new index with custom mappings from config, ignore if it's already created
    # new index will be created for everyday YMV
    suffix = datetime.strftime(datetime.now(), '%Y-%m-%d')
    resp = es_client.indices.create(index="epilot-cloud-cloudfront-logs" +
                                    suffix, body=config['es_mapping'],
                                    ignore=400)
    print resp

    # create a s3 boto client
    s3_client = boto3.client('s3')

    # split bucket and filepath to variables
    bucket = event['Records'][0]['s3']['bucket']['name']
    key = event['Records'][0]['s3']['object']['key']

    # set the file path
    file_path = '/tmp/cflogfile.gz'

    # download the gzip log from s3
    s3_client.download_file(bucket, key, file_path)

    # parse the log
    record_set = parse_log('/tmp/cflogfile.gz')

    # write the dict to ES
    resp = write_bulk(record_set, es_client, config)
    print resp
