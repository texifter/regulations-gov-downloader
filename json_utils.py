import json


def write_json_output(filepath, data):
    with open(filepath, 'w', encoding='utf-8') as outfile:
        json.dump(data, outfile)
