import os

TEMP_FOLDER = os.getenv('TEMP_FOLDER', './_temp')

if not os.path.exists(TEMP_FOLDER):
        os.makedirs(TEMP_FOLDER)


def clean_and_remodel_json(data):
    #check to see if there was an error or not
    if isinstance(data, str):
        return data     #System Info:...

    refined_json = {
        'total_results': data.get('total', 0),
        'number_of_results_in_the_page': data.get('count', 0),
        'items': []
    }

    useful_categories = ['active', 'public', 'createdAt', 'updatedAt', 'startDate', 'dueDate', 'percentageDone']
    useful_links = ['type', 'status', 'priority', 'project', 'author', 'assignee', 'version', 'parent']
    all_elements = data.get('_embedded', {}).get('elements', [])

    if all_elements:
        
        for item in all_elements:
            reduced_item = {}
            reduced_item['type'] = item.get('_type')
            reduced_item['id'] = item.get('id')

            #check to see if it's a project or a workpackage
            if reduced_item['type'] == 'Project':
                reduced_item['name'] = item.get('name')

            else:
                reduced_item['subject'] = item.get('subject')
            
            #the description can be find in the raw section as simple text
            reduced_item['description'] = item.get('description').get('raw')
    
            for cat in useful_categories:
                if cat in item and item[cat] is not None:
                     reduced_item[cat] = item[cat]

            links = item.get('_links', {})

            for l in useful_links:
                if l in links:
                    title = links[l].get('title')
                    if title:
                        reduced_item[l] = title

            refined_json['items'].append(reduced_item) #appends the item containg only important info to the final json

    return refined_json
