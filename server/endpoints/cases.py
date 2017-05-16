import json
import os
from flask import request, current_app
from flask_security import auth_token_required, roles_accepted
import core.case.database as case_database
import core.case.subscription as case_subscription
from server import forms
from core.case.subscription import CaseSubscriptions, add_cases, delete_cases, \
    rename_case
import core.config.config
import core.config.paths
from core.helpers import construct_workflow_name_key
from apscheduler.events import EVENT_JOB_EXECUTED, EVENT_JOB_ERROR, EVENT_JOB_ADDED, EVENT_JOB_REMOVED, \
    EVENT_SCHEDULER_START, EVENT_SCHEDULER_SHUTDOWN, EVENT_SCHEDULER_PAUSED, EVENT_SCHEDULER_RESUMED


def read_all_cases():
    from server.flaskserver import running_context

    @auth_token_required
    @roles_accepted(*running_context.user_roles['/cases'])
    def __func():
        return case_database.case_db.cases_as_json()
    return __func()


def create_case(case):
    from server.flaskserver import running_context

    @auth_token_required
    @roles_accepted(*running_context.user_roles['/cases'])
    def __func():
        case_obj = CaseSubscriptions()
        add_cases({"{0}".format(str(case)): case_obj})
        case_obj = running_context.CaseSubscription.query.filter_by(name=case).first()
        if not case_obj:
            running_context.db.session.add(running_context.CaseSubscription(name=case))
            running_context.db.session.commit()
            current_app.logger.debug('Case added: {0}'.format(case))
        return case_subscription.subscriptions_as_json()
    return __func()


def read_case(case):
    from server.flaskserver import running_context

    @auth_token_required
    @roles_accepted(*running_context.user_roles['/cases'])
    def __func():
        case_obj = case_database.case_db.session.query(case_database.Case) \
            .filter(case_database.Case.name == case).first()
        if case_obj:
            return {'case': case_obj.as_json()}
        else:
            return {'status': 'Case with given name does not exist'}
    return __func()


def update_case(case):
    from server.flaskserver import running_context

    @auth_token_required
    @roles_accepted(*running_context.user_roles['/cases'])
    def __func():
        form = forms.EditCaseForm(request.form)
        if form.name.data:
            rename_case(case, form.name.data)
            case_obj = running_context.CaseSubscription.query.filter_by(name=case).first()
            if case_obj:
                case_obj.name = form.name.data
                running_context.db.session.commit()

            if form.note.data:
                case_database.case_db.edit_case_note(form.name.data, form.note.data)
            current_app.logger.debug('Case name changed from {0} to {1}'.format(case, form.name.data))
        # TODO: YAML says that name AND note are required...is this second branch necessary?
        elif form.note.data:
            case_database.case_db.edit_case_note(case, form.note.data)
        return case_database.case_db.cases_as_json()
    return __func()


def delete_case(case):
    from server.flaskserver import running_context

    @auth_token_required
    @roles_accepted(*running_context.user_roles['/cases'])
    def __func():
        delete_cases([case])
        case_obj = running_context.CaseSubscription.query.filter_by(name=case).first()
        if case_obj:
            running_context.db.session.delete(case_obj)
            running_context.db.session.commit()
            current_app.logger.debug('Case deleted {0}'.format(case))
        return case_subscription.subscriptions_as_json()
    return __func()


def import_cases():
    from server.flaskserver import running_context

    @auth_token_required
    @roles_accepted(*running_context.user_roles['/cases'])
    def __func():
        form = forms.ImportCaseForm(request.form)
        filename = form.filename.data if form.filename.data else core.config.paths.default_case_export_path
        if os.path.isfile(filename):
            try:
                with open(filename, 'r') as cases_file:
                    cases_file = cases_file.read()
                    cases_file = cases_file.replace('\n', '')
                    cases = json.loads(cases_file)
                case_subscription.add_cases(cases)
                for case in cases.keys():
                    running_context.db.session.add(running_context.CaseSubscription(name=case))
                    running_context.CaseSubscription.update(case)
                    running_context.db.session.commit()
                return {"status": "success", "cases": case_subscription.subscriptions_as_json()}
            except (OSError, IOError) as e:
                current_app.logger.error('Error importing cases from file {0}: {1}'.format(filename, e))
                return {"status": "error reading file"}
            except ValueError as e:
                current_app.logger.error('Error importing cases from file {0}: Invalid JSON {1}'.format(filename, e))
                return {"status": "file contains invalid JSON"}
        else:
            current_app.logger.debug('Cases successfully imported from {0}'.format(filename))
            return {"status": "error: file does not exist"}
    return __func()


def export_cases():
    from server.flaskserver import running_context

    @auth_token_required
    @roles_accepted(*running_context.user_roles['/cases'])
    def __func():
        form = forms.ExportCaseForm(request.form)
        filename = form.filename.data if form.filename.data else core.config.paths.default_case_export_path
        try:
            with open(filename, 'w') as cases_file:
                cases_file.write(json.dumps(case_subscription.subscriptions_as_json()))
            current_app.logger.debug('Cases successfully exported to {0}'.format(filename))
            return {"status": "success"}
        except (OSError, IOError) as e:
            current_app.logger.error('Error exporting cases to {0}: {1}'.format(filename, e))
            return {"status": "error writing to file"}
    return __func()


def read_all_subscriptions():
    from server.flaskserver import running_context

    @auth_token_required
    @roles_accepted(*running_context.user_roles['/cases'])
    def __func():
        return case_subscription.subscriptions_as_json()
    return __func()


def read_all_events(case):
    from server.flaskserver import running_context

    @auth_token_required
    @roles_accepted(*running_context.user_roles['/cases'])
    def __func():
        result = case_database.case_db.case_events_as_json(case)
        return result
    return __func()


def create_subscription(case, element):
    from server.flaskserver import running_context

    @auth_token_required
    @roles_accepted(*running_context.user_roles['/cases'])
    def __func():
        events = element['events']
        if len(element['ancestry']) == 1 and events:
            events = convert_scheduler_events(events)
        converted_ancestry = convert_ancestry(element['ancestry'])
        case_subscription.add_subscription(case, converted_ancestry, events)
        running_context.CaseSubscription.update(case)
        running_context.db.session.commit()
        current_app.logger.debug('Subscription added for {0} to {1}'.format(converted_ancestry, events))
        return case_subscription.subscriptions_as_json()
    return __func()


def read_subscription(case):
    from server.flaskserver import running_context

    @auth_token_required
    @roles_accepted(*running_context.user_roles['/cases'])
    def __func():
        if case in core.case.subscription.subscriptions:
            result = core.case.subscription.subscriptions[case].as_json(names=True)
            return result
    return __func()


def convert_ancestry(ancestry):
    if len(ancestry) >= 3:
        ancestry[1] = construct_workflow_name_key(ancestry[1], ancestry[2])
        del ancestry[2]
    return ancestry

__scheduler_event_conversion = {'Scheduler Start': EVENT_SCHEDULER_START,
                                'Scheduler Shutdown': EVENT_SCHEDULER_SHUTDOWN,
                                'Scheduler Paused': EVENT_SCHEDULER_PAUSED,
                                'Scheduler Resumed': EVENT_SCHEDULER_RESUMED,
                                'Job Added': EVENT_JOB_ADDED,
                                'Job Removed': EVENT_JOB_REMOVED,
                                'Job Executed': EVENT_JOB_EXECUTED,
                                'Job Error': EVENT_JOB_ERROR}


def convert_scheduler_events(events):
    return [__scheduler_event_conversion[event] for event in events if event in __scheduler_event_conversion]


def convert_to_event_names(events):
    result = []
    for event in events:
        for key in __scheduler_event_conversion:
            if __scheduler_event_conversion[key] == event:
                result.append(key)
    return result


def update_subscription(case, element):
    from server.flaskserver import running_context

    @auth_token_required
    @roles_accepted(*running_context.user_roles['/cases'])
    def __func(element):
        ancestry = convert_ancestry(element['ancestry'])
        if len(ancestry) == 1 and element['events']:
            element['events'] = convert_scheduler_events(element['events'])
        success = case_subscription.edit_subscription(case, ancestry, element['events'])
        running_context.CaseSubscription.update(case)
        running_context.db.session.commit()
        if success:
            current_app.logger.info('Edited subscription {0} to {1}'.format(ancestry, element['events']))
            return case_subscription.subscriptions_as_json()
        else:
            current_app.logger.error('Error occurred while editing subscription '
                                     '{0} to {1}'.format(ancestry, element['events']))
            return {"status": "Error occurred while editing subscription"}
    return __func(element)


def delete_subscription(case, ancestry):
    from server.flaskserver import running_context

    @auth_token_required
    @roles_accepted(*running_context.user_roles['/cases'])
    def __func():
        converted_ancestry = convert_ancestry(ancestry['ancestry'])
        case_subscription.remove_subscription_node(case, converted_ancestry)
        running_context.CaseSubscription.update(case)
        running_context.db.session.commit()
        current_app.logger.debug('Deleted subscription {0}'.format(converted_ancestry))
        return case_subscription.subscriptions_as_json()
    return __func()
