import json
import random

elements = []
for i in range(1, 26):
    assignee = random.choice(["Alba Pellegrini", "Mario Rossi", "Claudio Neri"])
    status = random.choice(["New", "In Progress", "Closed", "Rejected"])
    
    new_item = {
        "type": "Task",
        "id": 100 + i,
        "subject": f"Task number {i}",
        "description": "2026-03-13T11:12:15.019Z",
        "createdAt": "2026-04-13T11:10:34.239Z",
        "status": status,
        "priority": "Normal",
        "project": "Mobile App",
        "author": "Alba Pellegrini",
        "assignee": assignee
    }
    elements.append(new_item)

fake_json = {
    "total_results": 45,
    "number_of_results_in_the_page": 25,
    "items": elements
}

with open("stress_test.json", "w") as f:
    json.dump(fake_json, f, indent=4)