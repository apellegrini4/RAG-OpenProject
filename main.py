from structured_URL_generator import build_OP_URL, fetch_openproject_data, chain, parser
from json_pruning import clean_and_remodel_json
from response_generator import generate_response
import json

def run(user_query):
    try:
        json_params = chain.invoke({"format_instructions": parser.get_format_instructions(),
                                    "user_query": user_query})
    except Exception as e:
        print('error: ', e)

    #------------DEBUG------------
    print('DEBUG - json filters:', json_params)


    url = build_OP_URL(json_params)
    # data = fetch_openproject_data(url)
    # final_data = clean_and_remodel_json(data)

    # print(f'Question: {user_query}')
    # print(final_data)
    # final_answer = generate_response(user_query, final_data)
    # print(f'Answer: {final_answer}')

    with open("tests/stress_test.json", "r") as f:
        final_data = json.load(f)
    # ---------------------------------------
    print(f'Question: {user_query}')

    total = final_data.get('total_results', 0)
    page = final_data.get('number_of_results_in_the_page', 0)
    if total > page: final_data['pagination_warning'] = f"I found {total} results but I'm only showing you the {page} recent ones."

    final_answer = generate_response(user_query, final_data)
    print(f'\nAnswer:\n{final_answer}')

if __name__ == '__main__':
    #query = "Show me all open bugs assigned to me"
    #query = "What open bugs are assigned to Mario Rossi?"
    #query = "Give me a summary of all the tasks in the Website Migration project."
    #query = "Are there any tasks in the Internal Audit project?"

    query = "Give me a summary all the tasks in the Mobile App project."
    run(query)