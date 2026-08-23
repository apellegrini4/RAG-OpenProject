#how many results a read asks for. Lowered from 7 to 5 after a pilot run, 
# on lists of six or seven items the answering model started dropping the last ones
PAGE_SIZE = 5


def pagination_warning(data):
    """ the sentence to append when a read found more than a page, or None. A single resource and
    a failed read both have no 'total_results' and fall through """
    if not isinstance(data, dict) or 'total_results' not in data:
        return None

    total = data['total_results']
    if total > PAGE_SIZE:
        return f"I found {total} results, these are the {PAGE_SIZE} most recently created."
    return None


#fields kept from a single Project or WorkPackage element
project_categories = ['active', 'public']
workpackage_categories = ['startDate', 'dueDate', 'percentageDone']
useful_links = ['type', 'status', 'priority', 'project', 'author', 'assignee', 'version']


def _reduce_item(item):
    reduced_item = {}

    reduced_item['entity'] = item.get('_type')
    reduced_item['id'] = item.get('id')

    #check to see if it's a project or a workpackage
    is_project = reduced_item['entity'] == 'Project'
    if is_project:
        reduced_item['name'] = item.get('name')
    else:
        reduced_item['subject'] = item.get('subject')

    description = item.get('description')
    if description and description.get('raw'):
        reduced_item['description'] = description['raw']

    for cat in (project_categories if is_project else workpackage_categories):
        if item.get(cat) is not None:
            reduced_item[cat] = item[cat]

    links = item.get('_links', {}) or {}

    for l in useful_links:
        link = links.get(l)
        title = link.get('title') if link else None
        if title:
            reduced_item[l] = title

    return reduced_item


def clean_and_remodel_json(data):
    #check to see if there was an error or not
    if isinstance(data, str):
        return {"error_message": data}     #System Info:...

    refined_json = {
        'total_results': data.get('total', 0),
        'number_of_results_in_the_page': data.get('count', 0),
        'items': []
    }

    all_elements = data.get('_embedded', {}).get('elements', [])

    for item in all_elements:
        #appends the item containg only important info to the final json
        refined_json['items'].append(_reduce_item(item))

    return refined_json


def clean_created_resource(data):
    """ same output shape as clean_and_remodel_json(), for the single resource commit_write()
    returns after a real create/update, not a list response, so it has no '_embedded.elements'
    and clean_and_remodel_json() would see it as an empty page """
    if isinstance(data, str):
        return {"error_message": data}

    return {
        'total_results': 1,
        'number_of_results_in_the_page': 1,
        'items': [_reduce_item(data)],
    }
