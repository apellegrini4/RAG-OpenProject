import os

TEMP_FOLDER = os.getenv('TEMP_FOLDER', './_temp')

if not os.path.exists(TEMP_FOLDER):
        os.makedirs(TEMP_FOLDER)


def clean_and_remodel_json():
    pass
