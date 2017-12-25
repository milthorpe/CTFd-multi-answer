from CTFd.plugins.keys import get_key_class, KEY_CLASSES, BaseKey
from CTFd.plugins import challenges, register_plugin_assets_directory
from flask import request, redirect, jsonify, url_for, session, abort
from CTFd.models import db, Challenges, WrongKeys, Keys, Teams, Awards, Solves, Files, Tags
from CTFd import utils
import logging
import time
from CTFd.plugins.challenges import get_chal_class


class CTFdMultiAnswerChallenge(challenges.BaseChallenge):
    """multi-answer allows right and wrong answers and leaves the question open"""
    id = "multianswer"
    name = "multianswer"

    templates = {  # Handlebars templates used for each aspect of challenge editing & viewing
        'create': '/plugins/CTFd-multi-answer/assets/multianswer-challenge-create.njk',
        'update': '/plugins/CTFd-multi-answer/assets/multianswer-challenge-update.njk',
        'modal': '/plugins/CTFd-multi-answer/assets/multianswer-challenge-modal.njk',
    }
    scripts = {  # Scripts that are loaded when a template is loaded
        'create': '/plugins/CTFd-multi-answer/assets/multianswer-challenge-create.js',
        'update': '/plugins/CTFd-multi-answer/assets/multianswer-challenge-update.js',
        'modal': '/plugins/CTFd-multi-answer/assets/multianswer-challenge-modal.js',
    }

    @staticmethod
    def create(request):
        """
        This method is used to process the challenge creation request.

        :param request:
        :return:
        """
        # Create challenge
        chal = MultiAnswerChallenge(
            name=request.form['name'],
            description=request.form['description'],
            value=request.form['value'],
            category=request.form['category'],
            type=request.form['chaltype']
        )

        if 'hidden' in request.form:
            chal.hidden = True
        else:
            chal.hidden = False

        max_attempts = request.form.get('max_attempts')
        if max_attempts and max_attempts.isdigit():
            chal.max_attempts = int(max_attempts)

        db.session.add(chal)
        db.session.commit()

        flag = Keys(chal.id, request.form['key'], request.form['key_type[0]'])
        if request.form.get('keydata'):
            flag.data = request.form.get('keydata')
        db.session.add(flag)

        db.session.commit()

        files = request.files.getlist('files[]')
        for f in files:
            utils.upload_file(file=f, chalid=chal.id)

        db.session.commit()

    @staticmethod
    def update(challenge, request):
        """
        This method is used to update the information associated with a challenge. This should be kept strictly to the
        Challenges table and any child tables.

        :param challenge:
        :param request:
        :return:
        """
        challenge.name = request.form['name']
        challenge.description = request.form['description']
        challenge.value = int(request.form.get('value', 0)) if request.form.get('value', 0) else 0
        challenge.max_attempts = int(request.form.get('max_attempts', 0)) if request.form.get('max_attempts', 0) else 0
        challenge.category = request.form['category']
        challenge.hidden = 'hidden' in request.form
        db.session.commit()
        db.session.close()

    @staticmethod
    def read(challenge):
        """
        This method is in used to access the data of a challenge in a format processable by the front end.

        :param challenge:
        :return: Challenge object, data dictionary to be returned to the user
        """
        challenge = MultiAnswerChallenge.query.filter_by(id=challenge.id).first()
        data = {
            'id': challenge.id,
            'name': challenge.name,
            'value': challenge.value,
            'description': challenge.description,
            'category': challenge.category,
            'hidden': challenge.hidden,
            'max_attempts': challenge.max_attempts,
            'type': challenge.type,
            'type_data': {
                'id': CTFdMultiAnswerChallenge.id,
                'name': CTFdMultiAnswerChallenge.name,
                'templates': CTFdMultiAnswerChallenge.templates,
                'scripts': CTFdMultiAnswerChallenge.scripts,
            }
        }
        return challenge, data

    @staticmethod
    def delete(challenge):
        """
        This method is used to delete the resources used by a challenge.

        :param challenge:
        :return:
        """
        # Needs to remove awards data as well
        WrongKeys.query.filter_by(chalid=challenge.id).delete()
        Solves.query.filter_by(chalid=challenge.id).delete()
        Keys.query.filter_by(chal=challenge.id).delete()
        files = Files.query.filter_by(chal=challenge.id).all()
        for f in files:
            utils.delete_file(f.id)
        Files.query.filter_by(chal=challenge.id).delete()
        Tags.query.filter_by(chal=challenge.id).delete()
        Challenges.query.filter_by(id=challenge.id).delete()
        db.session.commit()

    def attempt(chal, request):
        """
        This method is used to check whether a given input is right or wrong. It does not make any changes and should
        return a boolean for correctness and a string to be shown to the user. It is also in charge of parsing the
        user's input from the request itself.

        :param chal: The Challenge object from the database
        :param request: The request the user submitted
        :return: (boolean, string)
        """
        provided_key = request.form['key'].strip()
        chal_keys = Keys.query.filter_by(chal=chal.id).all()
        for chal_key in chal_keys:
            if get_key_class(chal_key.type).compare(chal_key.flag, provided_key):
                if chal_key.type == "static":
                    return True, 'Correct'
                elif chal_key.type == "wrong":
                    return False, 'Incorrect'
        return False, 'Incorrect'

    @staticmethod
    def solve(team, chal, request):
        """
        This method is used to insert Solves into the database in order to mark a challenge as solved.

        :param team: The Team object from the database
        :param chal: The Challenge object from the database
        :param request: The request the user submitted
        :return:
        """
        provided_key = request.form['key'].strip()
        solve = Solves(teamid=team.id, chalid=chal.id, ip=utils.get_ip(req=request), flag=provided_key)
        db.session.add(solve)
        db.session.commit()
        db.session.close()

    @staticmethod
    def fail(team, chal, request):
        """
        This method is used to insert WrongKeys into the database in order to mark an answer incorrect.

        :param team: The Team object from the database
        :param chal: The Challenge object from the database
        :param request: The request the user submitted
        :return:
        """
        provided_key = request.form['key'].strip()
        wrong = WrongKeys(teamid=team.id, chalid=chal.id, ip=utils.get_ip(request), flag=provided_key)
        db.session.add(wrong)
        db.session.commit()
        db.session.close()

    def wrong(team, chal, request):
        """Fail if the question is wrong record it and record the wrong answer to deduct points"""
        provided_key = request.form['key'].strip()
        wrong_value = 0
        wrong_value -= chal.value
        wrong = WrongKeys(teamid=team.id, chalid=chal.id, ip=utils.get_ip(request), flag=provided_key)
        solve = Awards(teamid=team.id, name=chal.id, value=wrong_value)
        solve.description = provided_key
        db.session.add(wrong)
        db.session.add(solve)
        db.session.commit()
        db.session.close()


class CTFdWrongKey(BaseKey):
    """Wrong key to deduct points from the player"""
    id = 2
    name = "wrong"
    templates = {  # Handlebars templates used for key editing & viewing
        'create': '/plugins/CTFd-multi-answer/assets/create-wrong-modal.njk',
        'update': '/plugins/CTFd-multi-answer/assets/edit-wrong-modal.njk',
    }

    def compare(saved, provided):
        """Compare the saved and provided keys"""
        if len(saved) != len(provided):
            return False
        result = 0
        for x, y in zip(saved, provided):
            result |= ord(x) ^ ord(y)
        return result == 0


def open_multihtml():
    with open('CTFd/plugins/CTFd-multi-answer/assets/multiteam.html') as multiteam:
        multiteam_string = str(multiteam.read())
    multiteam.close()
    return multiteam_string


class MultiAnswerChallenge(Challenges):
    __mapper_args__ = {'polymorphic_identity': 'multianswer'}
    id = db.Column(None, db.ForeignKey('challenges.id'), primary_key=True)
    initial = db.Column(db.Integer)

    def __init__(self, name, description, value, category, type='multianswer'):
        self.name = name
        self.description = description
        self.value = value
        self.initial = value
        self.category = category
        self.type = type


def chal(chalid):
    """Custom chal function to override challenges.chal when multianswer is used"""
    if utils.ctf_ended() and not utils.view_after_ctf():
        abort(403)
    if not utils.user_can_view_challenges():
        return redirect(url_for('auth.login', next=request.path))
    if (utils.authed() and utils.is_verified() and (utils.ctf_started() or utils.view_after_ctf())) or utils.is_admin():
        team = Teams.query.filter_by(id=session['id']).first()
        fails = WrongKeys.query.filter_by(teamid=session['id'], chalid=chalid).count()
        logger = logging.getLogger('keys')
        data = (time.strftime("%m/%d/%Y %X"), session['username'].encode('utf-8'), request.form['key'].encode('utf-8'), utils.get_kpm(session['id']))
        print("[{0}] {1} submitted {2} with kpm {3}".format(*data))

        chal = Challenges.query.filter_by(id=chalid).first_or_404()
        chal_class = get_chal_class(chal.type)

        # Anti-bruteforce / submitting keys too quickly
        if utils.get_kpm(session['id']) > 10:
            if utils.ctftime():
                chal_class.fail(team=team, chal=chal, request=request)
            logger.warning("[{0}] {1} submitted {2} with kpm {3} [TOO FAST]".format(*data))
            # return '3' # Submitting too fast
            return jsonify({'status': 3, 'message': "You're submitting keys too fast. Slow down."})

        solves = Awards.query.filter_by(teamid=session['id'], name=chalid,
                                        description=request.form['key'].strip()).first()
        try:
            flag_value = solves.description
        except AttributeError:
            flag_value = ""
        # Challange not solved yet
        if request.form['key'].strip() != flag_value or not solves:
            chal = Challenges.query.filter_by(id=chalid).first_or_404()
            provided_key = request.form['key'].strip()
            saved_keys = Keys.query.filter_by(chal=chal.id).all()

            # Hit max attempts
            max_tries = chal.max_attempts
            if max_tries and fails >= max_tries > 0:
                return jsonify({
                    'status': 0,
                    'message': "You have 0 tries remaining"
                })

            status, message = chal_class.attempt(chal, request)
            if status:  # The challenge plugin says the input is right
                if utils.ctftime() or utils.is_admin():
                    chal_class.solve(team=team, chal=chal, request=request)
                logger.info("[{0}] {1} submitted {2} with kpm {3} [CORRECT]".format(*data))
                return jsonify({'status': 1, 'message': message})
            elif message == "Failed Attempt":
                if utils.ctftime() or utils.is_admin():
                    chal_class.wrong(team=team, chal=chal, request=request)
                logger.info("[{0}] {1} submitted {2} with kpm {3} [Failed Attempt]".format(*data))
                return jsonify({'status': 1, 'message': message})
            else:  # The challenge plugin says the input is wrong
                if utils.ctftime() or utils.is_admin():
                    chal_class.fail(team=team, chal=chal, request=request)
                logger.info("[{0}] {1} submitted {2} with kpm {3} [WRONG]".format(*data))
                # return '0' # key was wrong
                if max_tries:
                    attempts_left = max_tries - fails - 1  # Off by one since fails has changed since it was gotten
                    tries_str = 'tries'
                    if attempts_left == 1:
                        tries_str = 'try'
                    if message[-1] not in '!().;?[]\{\}':  # Add a punctuation mark if there isn't one
                        message = message + '.'
                    return jsonify({'status': 0, 'message': '{} You have {} {} remaining.'.format(message, attempts_left, tries_str)})
                else:
                    return jsonify({'status': 0, 'message': message})

        # Challenge already solved
        else:
            logger.info("{0} submitted {1} with kpm {2} [ALREADY SOLVED]".format(*data))
            # return '2' # challenge was already solved
            return jsonify({'status': 2, 'message': 'You already solved this'})
    else:
        return jsonify({
            'status': -1,
            'message': "You must be logged in to solve a challenge"
        })


def load(app):
    """load overrides for multianswer plugin to work properly"""
    app.db.create_all()
    register_plugin_assets_directory(app, base_path='/plugins/CTFd-multi-answer/assets/')
    #utils.override_template('team.html', open_multihtml())
    challenges.CHALLENGE_CLASSES["multianswer"] = CTFdMultiAnswerChallenge
    KEY_CLASSES["wrong"] = CTFdWrongKey
    #app.view_functions['challenges.chal'] = chal
