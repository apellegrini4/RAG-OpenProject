def clean_and_remodel_json(data):
    #check to see if there was an error or not
    if isinstance(data, str):
        return {"error_message": data}     #System Info:...

    refined_json = {
        'total_results': data.get('total', 0),
        'number_of_results_in_the_page': data.get('count', 0),
        'items': []
    }

    project_categories = ['active', 'public']
    workpackage_categories = ['startDate', 'dueDate', 'percentageDone']

    useful_links = ['type', 'status', 'priority', 'project', 'author', 'assignee', 'version']
    all_elements = data.get('_embedded', {}).get('elements', [])

    for item in all_elements:
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

        links = item.get('_links', {})

        for l in useful_links:
            if l in links:
                title = links[l].get('title')
                if title:
                    reduced_item[l] = title

        refined_json['items'].append(reduced_item) #appends the item containg only important info to the final json

    return refined_json
