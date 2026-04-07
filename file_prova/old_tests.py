#--------queries and test sets for 
#QUERIES SECTION
#first test set
#test_queries = [
#    "Show me all active and public projects.",
#    "Search for the project named Data Migration.",
#
#    "Find the tasks assigned to Mario Rossi.",
#    "What are the open bugs?",
#
#    "Find the urgent milestones or features in the Alpha project.",
#    "Show me the tasks created by Alba that are 100'%' completed.",
#
#    "Give me the list of all registered users in the system.",
#    "Search for the work package with ID 42."
#]
#
##new test set to verify the model ability to understand and adapt
blind_test_queries = [
    "Show me the closed features in the Beta project that were created by Alba and assigned to Mario.",
    
    "I need to see the work package number 99.",
    
    "What is the total financial budget for the Data Migration project?",
    
    #OR condition, not possible to do it in OpenProject (TO DO: decide if u wanna keep it or not as exemple)
    "Find tasks assigned to Alba that are either urgent or 50% completed."

]

#new test set queries
second_test_set_queries = [
    #(status, type, assignee, project)
    "Show me all open bug assigned to Alba Pellegrini in the project E-commerce Redesign.",
    
    #mixed text search (subject, project)
    "Search for task that containes the word 'database' in the title inside the project E-commerce Redesign.",
    
    #aearch by author
    "Show me the tasks created by Alba Pellegrini which have High priority.",
    
    #general search of projects
    "Give me the list of all active and public projects.",
    
    #search without project or assignee
    "What are the closed features with normal priority."
]

#TEST SECTION
#generated_output = []
#for i, q in enumerate(second_test_set_queries):
#    print(f"query {i+1}: ", {q})
#    try:
#        generated_output.append(chain.invoke({"format_instructions": parser.get_format_instructions(), "user_query": q}))
#    except Exception as e:
#        print('error: ', e)
#    
#for i, go in enumerate(generated_output):
#    #print(f'test: {i+1}')
#    url = build_OP_URL(go)
#
#    data = fetch_openproject_data(url)
#
#    final_data = clean_and_remodel_json(data)
#    #with open(f"Data-Q{i}.json", "w") as file: #code to check the json obtained
#    #    json.dump(data, file, indent=4)
#    #with open(f"Data-Q{i}_PRUNED.json", "w", encoding="utf-8") as file:
#    #    json.dump(final_data, file, indent=4, ensure_ascii=False)


#----------test for response generator----------
#TEMPORARY TEST
#if __name__ == "__main__":
#    #example
#    mock_pruned_json = {
#        "total_results": 3,
#        "number_of_results_in_the_page": 3,
#        "items": [
#            {
#                "type_entity": "WorkPackage",
#                "id": 37,
#                "subject": "task1",
#                "createdAt": "2026-03-13T10:55:08.576Z",
#                "type": "Bug",
#                "status": "Confirmed",
#                "priority": "High",
#                "project": "E-commerce Redesign",
#                "assignee": "Alba Pellegrini"
#            },
#
#            {
#                "type_entity": "WorkPackage",
#                "id": 42,
#                "subject": "task7",
#                "createdAt": "2026-03-13T10:55:08.576Z",
#                "type": "Bug",
#                "status": "Developed",
#                "priority": "Low",
#                "project": "E-commerce Redesign",
#                "assignee": "Alba Pellegrini"
#            },
#
#            {
#                "type_entity": "WorkPackage",
#                "id": 73,
#                "subject": "task9",
#                "createdAt": "2026-03-13T10:55:08.576Z",
#                "type": "Bug",
#                "status": "Test failed",
#                "priority": "Medium",
#                "project": "E-commerce Redesign",
#                "assignee": "Alba Pellegrini"
#            }
#        ]
#    }
#    
#    question = "Show me all open bug assigned to Alba Pellegrini in the project E-commerce Redesign."
#    
#    print("Processing response...\n")
#    final_response = generate_response(question, mock_pruned_json)
#    
#    print("--- RESPONSE ---")
#    print(final_response)