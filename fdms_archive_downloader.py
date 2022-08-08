import json
import os
import requests
import time
from rate_limited_fetcher import RateLimitedFetcher
from json_utils import write_json_output
from datetime import datetime

MAX_PAGES_PER_DATA_PAGE = 20
MAX_ITEMS_PER_DATA_PAGE = 250
MAX_ITEMS_PER_RESULT_BATCH = (MAX_PAGES_PER_DATA_PAGE*MAX_ITEMS_PER_DATA_PAGE)
API_ENDPOINT_BASE = 'https://api.regulations.gov/v4'


class FDMSArchiveDownloader:
    def __init__(self, logger, api_key, docket_id, output_directory, resume_download=True):
        self._logger = logger
        self._fetcher = RateLimitedFetcher(self._logger, 1000, api_key)
        self._docket_id = docket_id
        self._output_directory = output_directory
        self._resume = resume_download
        self._resume_info = {}

    def _try_load_resume_info(self):
        if not os.path.exists(self._output_directory):
            return {}
        resume_file = os.path.join(self._output_directory, '__resume_info.dat')
        if not os.path.exists(resume_file):
            return {}

        with open(resume_file) as resume_input:
            return json.load(resume_input)

    def _save_resume_info(self):
        if not os.path.exists(self._output_directory):
            os.makedirs(self._output_directory)
        resume_file = os.path.join(self._output_directory, '__resume_info.dat')
        write_json_output(resume_file, self._resume_info)

    def _get_all_data_pages(self, resource_url, query_params={}, include_page_count=False):
        ret = []
        page_number = 1
        while True:
            these_params = {**query_params, 'page[number]': page_number}
            this_response = self._fetcher.get_or_wait(
                resource_url, these_params)
            response_data = this_response.data

            if not response_data or 'data' not in response_data or len(response_data['data']) == 0:
                break

            ret.extend(response_data['data'])
            if not 'meta' in response_data:
                break
            if not 'hasNextPage' in response_data['meta']:
                break
            if not response_data['meta']['hasNextPage']:
                break
            page_number = page_number + 1

        if include_page_count:
            return ret, page_number
        return ret

    def _get_all_data_pages_for_comments(self, resource_url, document_object_id):
        # first - get all data pages
        query_params = {
            'filter[commentOnId]': document_object_id,
            'page[size]': MAX_ITEMS_PER_DATA_PAGE,
            'sort': 'lastModifiedDate,documentId'
        }
        ret = self._get_all_data_pages(resource_url, query_params)

        if len(ret) < MAX_ITEMS_PER_RESULT_BATCH:
            return ret

        # now, use the lastModifiedDate of the last document
        # to get further pages
        object_id_hash = {}
        for ret_item in ret:
            if not ret_item:
                continue
            object_id_hash[ret_item["id"]] = True

        while True:
            current_last_comment = ret[-1]
            last_modified_date = current_last_comment["attributes"]["lastModifiedDate"]
            last_modified_date_as_date = datetime.strptime(
                last_modified_date, '%Y-%m-%dT%H:%M:%SZ')
            query_params["filter[lastModifiedDate][ge]"] = str(
                last_modified_date_as_date)
            this_batch, page_count = self._get_all_data_pages(
                resource_url, query_params, True)

            if len(this_batch) == 0:
                break

            for item in this_batch:
                if item["id"] in object_id_hash:
                    continue
                ret.append(item)
                object_id_hash[item["id"]] = True

            if len(this_batch) < MAX_ITEMS_PER_RESULT_BATCH:
                break

        return ret

    def _get_comment_details_and_attachments(self, comment_id):
        query_params = {
            "include": "attachments"
        }
        details_response = self._fetcher.get_or_wait(
            f'{API_ENDPOINT_BASE}/comments/{comment_id}', query_params)
        return details_response.data

    def _save_attachments(self, comments_dir, comment_id, attachments):
        self._logger.info(
            f"-- saving attachments for: {comment_id}, {len(attachments)} attachments...")
        attachment_base = f'{comment_id}_attachments'
        full_attachment_path = os.path.join(comments_dir, attachment_base)
        if not os.path.exists(full_attachment_path):
            os.makedirs(full_attachment_path)

        ret = []
        for attachment in attachments:
            if ('attributes' in attachment and
                'fileFormats' in attachment['attributes']
                ):
                attachment_formats = attachment['attributes']['fileFormats']
                if not attachment_formats or attachment_formats is None:
                    continue

                for file_format in attachment['attributes']['fileFormats']:
                    if not 'fileUrl' in file_format:
                        continue
                    file_parts = file_format['fileUrl'].split('/')
                    if len(file_parts) < 2:
                        continue
                    response = requests.get(
                        file_format['fileUrl'], allow_redirects=True)
                    if not response or response.status_code > 299:
                        continue
                    filename = file_parts[-1]
                    full_path = os.path.join(full_attachment_path, filename)
                    open(full_path, 'wb').write(response.content)
                    ret.append(f'{attachment_base}/{filename}')

        return ret

    def _get_docket_details(self):
        docket_response = self._fetcher.get_or_wait(
            f'{API_ENDPOINT_BASE}/dockets/{self._docket_id}')
        return docket_response.data['data']

    def _get_docket_documents(self):
        documents_info = []
        if not self._resume or 'document_ids' not in self._resume_info:
            docket_documents = self._get_all_data_pages(f'{API_ENDPOINT_BASE}/documents', {
                'filter[docketId]': self._docket_id,
                'page[size]': MAX_ITEMS_PER_DATA_PAGE
            })
            write_json_output(os.path.join(
                self._output_directory, 'docket_documents.json'), docket_documents)
            for this_document in docket_documents:
                documents_info.append(
                    {"id": this_document['id'], "document_object_id": this_document['attributes']['objectId']})
            self._resume_info['document_ids'] = documents_info
        else:
            self._logger.info('- already have document ids, skipping...')
            documents_info = self._resume_info['document_ids']
        return documents_info

    def _gather_comment_ids(self, comments_dir, documents_info):
        all_comments = []
        total_document_count = len(documents_info)
        self._logger.info(
            f"-------- getting comments for all documents --------")
        self._logger.info(f"---- {total_document_count} total documents")
        for document in documents_info:
            document_id = document['id']
            document_object_id = document['document_object_id']
            document_object_key = f"doc_{document_object_id}"
            if not self._resume or document_object_key not in self._resume_info:
                self._logger.info(
                    f'-------- getting comments for document: {document_id}, objectId: {document_object_id}')
                comments = self._get_all_data_pages_for_comments(
                    f'{API_ENDPOINT_BASE}/comments', document_object_id)
                comments_filename = f'{document_id}_{document_object_id}_comments.json'
                write_json_output(os.path.join(
                    self._output_directory, comments_filename), comments)

                doc_comments = []
                for this_comment in comments:
                    doc_comments.append(this_comment['id'])
                    all_comments.append(this_comment['id'])
                self._resume_info[document_object_key] = doc_comments
            else:
                self._logger.info(
                    f"- already have document info for {document_object_key} - skipping...")
                all_comments.extend(self._resume_info[document_object_key])
        return all_comments

    def _gather_comments_and_attachments(self, comments_dir, all_comments):
        total_comments = len(all_comments)
        current_comment_index = 0
        comment_attachments = {}
        for comment_id in all_comments:
            current_comment_index = current_comment_index + 1
            if (current_comment_index % 100) == 0:
                current_percent = current_comment_index / total_comments
                percent_format = "{:.2%}".format(current_percent)
                self._logger.info(
                    f"---- retrieved {current_comment_index} of {total_comments} ({percent_format})")

            comment_id_key = f"comment_{comment_id}"
            if not self._resume or comment_id_key not in self._resume_info:
                self._logger.info(
                    f"--- getting comment details and attachments for: {comment_id}")
                comment = self._get_comment_details_and_attachments(comment_id)
                comment_details = comment['data']
                comment_filename = f"{comment_details['attributes']['commentOnDocumentId']}_{comment_id}.json"
                comment_outpath = os.path.join(
                    comments_dir, comment_filename)
                write_json_output(comment_outpath, comment_details)

                these_attachments = []
                if ('relationships' in comment_details and
                        'attachments' in comment_details['relationships'] and
                        'data' in comment_details['relationships']['attachments'] and
                    'included' in comment
                    ):

                    attachment_ids = list(
                        map(lambda x: x['id'], comment_details['relationships']['attachments']['data']))

                    attachments = list(
                        filter(lambda x: x['id'] in attachment_ids, comment['included']))

                    if attachments and len(attachments) > 0:
                        saved_filenames = self._save_attachments(
                            comments_dir, comment_id, attachments)
                        comment_attachments[comment_id] = []
                        for saved_filename in saved_filenames:
                            comment_attachments[comment_id].append(
                                saved_filename)
                            these_attachments.append(saved_filename)
                self._resume_info[comment_id_key] = these_attachments
            else:
                self._logger.info(
                    f"- already have comment details and attachments for {comment_id} - skipping...")
                comment_attachments[comment_id] = self._resume_info[comment_id_key]
        return comment_attachments

    def download_archive(self):
        self._logger.info('----------------')
        self._logger.info(f'output to: {self._output_directory}')
        self._logger.info('')

        start_time = time.time()
        try:
            if (self._resume):
                self._resume_info = self._try_load_resume_info()

            self._logger.info('-------- getting docket and details --------')
            if not self._resume or 'docket' not in self._resume_info:
                docket_details = self._get_docket_details()
                write_json_output(os.path.join(
                    self._output_directory, 'docket_details.json'), docket_details)
                self._resume_info['docket'] = docket_details['id']
            else:
                self._logger.info('- already have docket details, skipping...')

            documents_info = self._get_docket_documents()

            comments_dir = os.path.join(self._output_directory, 'comments')
            if not os.path.exists(comments_dir):
                os.makedirs(comments_dir)

            all_comments = self._gather_comment_ids(
                comments_dir, documents_info)

            self._logger.info(
                '-------- getting all comment details and attachments --------')

            total_comments = len(all_comments)
            self._logger.info(f"---- {total_comments} total comments")

            comment_attachments = self._gather_comments_and_attachments(
                comments_dir, all_comments)

            write_json_output(os.path.join(
                self._output_directory, 'comment_attachments.json'), comment_attachments)

            self._logger.info('-------- Done! --------')
        except Exception as e:
            import sys
            t, v, tb = sys.exc_info()
            raise v.with_traceback(tb)
        finally:
            self._save_resume_info()
            end_time = time.time()
            self._logger.info(f'total time taken: {end_time-start_time}')
