import argparse
import json
import os
import requests
import time
import math
import logging
import shutil
from datetime import datetime

from rate_limited_fetcher import RateLimitedFetcher
from fdms_archive_downloader import FDMSArchiveDownloader

DEFAULT_CONFIG_FILE = './config.json'

logFormatter = logging.Formatter("[%(asctime)s] %(message)s")
rootLogger = logging.getLogger()
rootLogger.setLevel(logging.DEBUG)

log_filename = f'{math.floor(time.time())}_fdms'

if not os.path.exists("./logs"):
    os.makedirs("./logs")

fileHandler = logging.FileHandler(f"./logs/{log_filename}.log")
fileHandler.setFormatter(logFormatter)
rootLogger.addHandler(fileHandler)

consoleHandler = logging.StreamHandler()
consoleHandler.setFormatter(logFormatter)
rootLogger.addHandler(consoleHandler)

logger = rootLogger


def load_configuration(config_file):
    with open(config_file) as config_input:
        config = json.load(config_input)

        if not 'api_key' in config:
            raise Exception("configuration is missing api_key")
        return config


def move_attachments(output_dir, attachment_outdir):
    logger.info('----------------')
    logger.info(f'copying spreadsheet attachements to: {attachment_outdir}')
    logger.info('')

    comments_dir = os.path.join(output_dir, 'comments')
    attachments_file = os.path.join(output_dir, 'comment_attachments.json')
    if not os.path.exists(attachment_outdir):
        os.makedirs(attachment_outdir)

    with open(attachments_file, 'r', encoding='utf-8') as f:
        attachment_data = json.load(f)

    for key, value in attachment_data.items():
        for attachment_file in value:
            if not attachment_file.endswith('.xlsx'):
                continue
            logger.info(f'moving: {attachment_file}')
            full_path = os.path.join(comments_dir, attachment_file)
            filename = os.path.basename(full_path)
            shutil.copy(full_path, attachment_outdir)

            path_in_outdir = os.path.join(attachment_outdir, filename)
            new_filename = f'{key}_{filename}'
            full_new_filename = os.path.join(attachment_outdir, new_filename)
            os.rename(path_in_outdir, full_new_filename)


headers_to_ignore = ["displayProperties", "comment"]


def extract_comment_headers(comment_data):
    ret = {}
    for key, value in comment_data.items():
        if key in headers_to_ignore:
            continue
        if not value:
            continue
        ret[key] = value
    return ret


def extract_comment_body(comment_data):
    if not "comment" in comment_data:
        return None
    return comment_data["comment"]


def extract_write_comment(output_dir, comment_data):
    if not comment_data or not "id" in comment_data or not "attributes" in comment_data or not "type" in comment_data:
        return
    comment_id = comment_data["id"]
    comment_headers = extract_comment_headers(comment_data["attributes"])
    comment_body = extract_comment_body(comment_data["attributes"])
    if not comment_body:
        return

    with open(os.path.join(output_dir, f"{comment_id}-comment.txt"), 'w', encoding='utf-8') as output:
        for key, value in comment_headers.items():
            output.write(f"{key}: {value}" + os.linesep)
        output.write(os.linesep)
        output.write(comment_body + os.linesep)


def extract_comments(output_dir, extract_output_dir):
    comments_path = os.path.join(output_dir, 'comments')
    if not os.path.exists(extract_output_dir):
        os.makedirs(extract_output_dir)

    for file in os.listdir(comments_path):
        if not file.endswith(".json"):
            continue
        with open(os.path.join(comments_path, file), 'r', encoding='utf-8') as f:
            comment_data = json.load(f)
            extract_write_comment(extract_output_dir, comment_data)


def get_comment_ids_from_documents(base_dir):
    path_to_documents = os.path.join(base_dir, 'docket_documents.json')
    with open(path_to_documents, 'r', encoding='utf-8') as f:
        documents_json = json.load(f)
    if not documents_json:
        return []
    ret = []
    for document in documents_json:
        doc_id = document["id"]
        object_id = document["attributes"]["objectId"]
        comment_list_file = os.path.join(
            base_dir, f'{doc_id}_{object_id}_comments.json')
        with open(comment_list_file, 'r', encoding='utf-8') as comment_input:
            comments_json = json.load(comment_input)
            for comment in comments_json:
                ret.append({
                    "file_id": f'{doc_id}_{comment["id"]}',
                    "doc_id": doc_id,
                    "comment_id": comment["id"]
                })
    return ret


def produce_outputdiff(output_dir, orig_outputdir, extractcommentsdir):
    old_comment_ids = get_comment_ids_from_documents(orig_outputdir)
    new_comment_ids = get_comment_ids_from_documents(output_dir)
    diff_ids = [i for i in new_comment_ids +
                old_comment_ids if i not in new_comment_ids or i not in old_comment_ids]
    if not extractcommentsdir:
        print(f'Missing IDs: {diff_ids}')
        return

    if not os.path.exists(extractcommentsdir):
        os.makedirs(extractcommentsdir)

    for this_id in diff_ids:
        comment_path = os.path.join(
            output_dir, 'comments', f'{this_id["file_id"]}.json')
        if not os.path.exists(comment_path):
            print(f'!! Could not find file for comment: {comment_path}')
            continue
        with open(comment_path, 'r', encoding='utf-8') as comment_input:
            comment_data = json.load(comment_input)
            extract_write_comment(extractcommentsdir, comment_data)
        attachment_dir = os.path.join(
            output_dir, f'comments', f'{this_id["comment_id"]}_attachments')
        if os.path.exists(attachment_dir):
            copy_attachment_dir = os.path.join(
                extractcommentsdir, f'{this_id["comment_id"]}_attachments')
            os.makedirs(copy_attachment_dir)
            (_, _, filenames) = next(os.walk(attachment_dir))
            for attachment in filenames:
                shutil.copy(os.path.join(attachment_dir,
                            attachment), copy_attachment_dir)


if __name__ == "__main__":
    start_time = time.time()
    parser = argparse.ArgumentParser()
    parser.add_argument("-m", "--moveattachments",
                        help="flag to move attachments")
    parser.add_argument("-o", "--output", help="output directory")
    parser.add_argument("-i", "--docketid", help="docket ID")
    parser.add_argument("-a", "--attachmentdir",
                        help="directory to move attachments to")
    parser.add_argument("-e", "--extractcommentsdir",
                        help="directory to extract comments to")
    parser.add_argument("-d", "--outputdiff",
                        help="directory diff with output")
    parser.add_argument("-c", "--config", help="path to config file")
    parser.add_argument("-n", "--noresume", dest='resume_download',
                        action="store_false", help="do not resume download if available")
    parser.set_defaults(resume_download=True)
    args = parser.parse_args()

    if not args.output:
        raise "missing output directory"

    if not os.path.exists(args.output):
        os.makedirs(args.output)

    if (args.outputdiff):
        produce_outputdiff(args.output, args.outputdiff,
                           args.extractcommentsdir)
    elif (args.moveattachments):
        move_attachments(args.output, args.attachmentdir)
    elif (args.extractcommentsdir):
        extract_comments(args.output, args.extractcommentsdir)
    else:
        if not args.docketid:
            raise "must include docket id"
        config_file_path = DEFAULT_CONFIG_FILE
        if args.config:
            config_file_path = args.config
        config = load_configuration(config_file_path)
        downloader = FDMSArchiveDownloader(logger, config['api_key'], args.docketid,
                                           args.output, args.resume_download)
        downloader.download_archive()
