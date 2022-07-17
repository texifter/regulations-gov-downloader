# Regulations.gov Docket Utilites

Utilities for downloading and working with dockets from the [Regulations.gov API](https://open.gsa.gov/api/regulationsgov/).

-   [Prerequisites](#Prerequisites)
-   [Environment Setup](#Environment-Setup)
-   [Downloading Dockets](#Downloading-Dockets)
-   [Additional Utilities](#Additional-Utilities)
-   [License](#License)

## Prerequisites

-   Python 3.6 or higher
-   An API key for the [Regulations.gov API](https://open.gsa.gov/api/regulationsgov/)

## Environment Setup

-   Create your virtual environment. E.g. : `python -m venv env`
-   Activate your environment (`source env/bin/activate`, or on Windows: `env\Scripts\activate`)
-   Install requirements: `pip install -r requirements.txt`
-   Update the [config.json](./config.json) with your API key from Regulations.gov

## Downloading Dockets

The primary purpose of the `extract_fdms_dockey.py` script is to download a complete docket archive from Regulations.gov. The downloader will attempt to retrieve all docket information, details, documents, and comments as well as document and comment attachments. Note that the use of the [Regulations.gov API](https://open.gsa.gov/api/regulationsgov/) may be rate-limited, and the downloader will account for this (and wait as necessary to ensure that it can obtain all the files).

Another aspect of the downloader script is the ability to resume a download if it is interrupted. This can be turned off by using the `-n` flag to not resume (but rather to start the docket gathering from fresh).

All documents and comments are downloaded as their `.json` files and structure is kept intact. Any attachment files are downloaded as their binary-file types.

```
Usage: python extract_fdms_docket.py -c {config_file} -o {output_directory} -i {docket_id} [-n|--noresume]
```

-   `config_file` : path to your configuration file (see [./config.json](./config.json) for example and options)
-   `output_directory` : base path to where to output the files
-   `docket_id` : the docket ID to download (e.g. `FDA-2009-N-0501-0012`)
-   `noresume` : (optional) if missing, the downloader will attempt to resume the gather from where it was last left off. Use this option to restart a gather of a docket from the start.

## Additional Utilities

### Move Downloaded Attachments

Once you have downloaded a docket, you can choose to move the attachment files out of the default downloaded path to another path.

```
Usage: python extract_fdms_docket.py -o {original_output_path} -a {new_path}
```

-   `original_output_path` : path where the original docket files were downloaded
-   `new_path` : new path to move the attachments to

### Extract Downloaded Comments

```
Usage: python extract_fdms_docket.py -o {original_output_path} -e {path_to_extract_to}
```

-   `original_output_path` : path where the original docket files were downloaded
-   `path_to_extract_to` : new path to extract the comments to

### Output Delta Between Two Downloaded Dockets

```
Usage: python extract_fdms_docket.py -o {original_output_path} -d {output_path_to_diff} -e {path_to_extract_to}
```

-   `original_output_path` : path where the original docket files were downloaded
-   `output_path_to_diff` : path where docket files to diff against are
-   `path_to_extract_to` : path to place the output

## License

This software is licensed under the MIT license (see the [LICENSE](./LICENSE) file).

By using this code, you assume all responsibility for any damages, additional charges, and all issues.
