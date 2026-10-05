"""Constrain workspace generation to the reviewed hierarchy, without authority fields."""


def obj(properties):
    return {'type': 'object', 'properties': properties,
            'required': list(properties), 'additionalProperties': False}


def string(limit, required=False):
    # Large bounded repetitions expand the native grammar's stack on Windows.
    # Enforce size limits in normalize_draft; generation constrains shape/content.
    return {'type': 'string', **({'minLength': 1} if required else {})}


def array(items, limit):
    return {'type': 'array', 'items': items}


TASK = obj({
    'key': string(80, True), 'title': string(300, True), 'description': string(10000, True),
    'priority': {'type': 'string', 'enum': ['low', 'medium', 'high']},
    'estimatedHours': {'type': 'number'},
    'estimatedDuration': string(100), 'requiredSkills': array(string(200), 20),
    'startDate': string(10), 'dueDate': string(10), 'officeKey': string(80),
    'sourceQuote': string(2000), 'dependencies': array(string(80, True), 100),
    'subitems': array(obj({'title': string(300, True), 'dueDate': string(10)}), 30),
})
WORKSPACE_DRAFT_SCHEMA = obj({
    'project': obj({'title': string(300), 'description': string(10000),
                    'objectives': string(10000), 'startDate': string(10), 'targetDate': string(10)}),
    'offices': array(obj({'key': string(80, True), 'name': string(200, True), 'evidence': string(2000, True)}), 100),
    'groups': array(obj({'title': string(120, True), 'color': string(7), 'tasks': array(TASK, 100)}), 30),
})
