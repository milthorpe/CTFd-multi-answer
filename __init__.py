from CTFd.plugins.flags import get_flag_class, FLAG_CLASSES, BaseFlag
from CTFd.plugins import register_plugin_assets_directory
from CTFd.plugins.challenges import CHALLENGE_CLASSES, BaseChallenge
from flask import session, Blueprint
from CTFd.models import db, Challenges, Fails, Flags, Awards, Solves, Files, Tags
from CTFd import utils
import logging

class MultiAnswerChallenge(Challenges):
    __mapper_args__ = {'polymorphic_identity': 'multianswer'}
    id = db.Column(
        db.Integer, db.ForeignKey("challenges.id", ondelete="CASCADE"), primary_key=True
    )
    initial = db.Column(db.Integer, default=0)

    def __init__(self, *args, **kwargs):
        super(DynamicChallenge, self).__init__(**kwargs)
        self.initial = kwargs["value"]

class CTFdMultiAnswerChallenge(BaseChallenge):
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
    # Route at which files are accessible. This must be registered using register_plugin_assets_directory()
    route = "/plugins/CTFd-multi-answer/assets/"
    # Blueprint used to access the static_folder directory.
    blueprint = Blueprint(
        "CTFd-multi-answer",
        __name__,
        template_folder="templates",
        static_folder="assets"
    )
    challenge_model = MultiAnswerChallenge

    @classmethod
    def update(cls, challenge, request):
        """
        This method is used to update the information associated with a challenge. This should be kept strictly to the
        Challenges table and any child tables.

        :param challenge:
        :param request:
        :return:
        """
        data = request.form or request.get_json()
        for attr, value in data.items():
            setattr(challenge, attr, value)

        db.session.commit()
        return challenge

    @classmethod
    def read(cls, challenge):
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
                'id': cls.id,
                'name': cls.name,
                'templates': cls.templates,
                'scripts': cls.scripts,
            }
        }
        return challenge, data

    @classmethod
    def attempt(cls, chal, request):
        """
        This method is used to check whether a given input is right or wrong. It does not make any changes and should
        return a boolean for correctness and a string to be shown to the user. It is also in charge of parsing the
        user's input from the request itself.

        :param chal: The Challenge object from the database
        :param request: The request the user submitted
        :return: (boolean, string)
        """
        data = request.form or request.get_json()
        submission = data["submission"].strip()
        flags = Flags.query.filter_by(challenge_id=challenge.id).all()
        for flag in flags:
            try:
                if get_flag_class(flag.type).compare(flag, submission):
                    if flag.type == "correct":
                        solves = Awards.query.filter_by(teamid=session['id'], name=chal.id,
                                                        description=submission).first()
                        try:
                            flag_value = solves.description
                        except AttributeError:
                            flag_value = ""
                        # Challenge not solved yet
                        if submission != flag_value or not solves:
                            solve = Awards(teamid=session['id'], name=chal.id, value=chal.value)
                            solve.description = submission
                            db.session.add(solve)
                            db.session.commit()
                            db.session.close()
                        return True, 'Correct'
                        # TODO Add description function call to the end of "Correct" in return
                    elif flag.type == "wrong":
                        solves = Awards.query.filter_by(teamid=session['id'], name=chal.id,
                                                        description=submission).first()
                        try:
                            flag_value = solves.description
                        except AttributeError:
                            flag_value = ""
                        # Challenge not solved yet
                        if submission != flag_value or not solves:
                            fail_value = 0
                            fail_value -= chal.value
                            fail = Fails(teamid=session['id'], chalid=chal.id, ip=utils.get_ip(request),
                                            flag=submission)
                            solve = Awards(teamid=session['id'], name=chal.id, value=fail_value)
                            solve.description = submission
                            db.session.add(fail)
                            db.session.add(solve)
                            db.session.commit()
                            db.session.close()
                        return False, 'Error'
                        # TODO Add description function call to the end of "Error" in return
            except FlagException as e:
                return False, e.message
        return False, 'Incorrect'

    @classmethod
    def solve(cls, user, team, chal, request):
        """This method is not used"""
    @classmethod
    def fail(cls, user, team, chal, request):
        """This method is not used"""


class CTFdWrongFlag(BaseFlag):
    """Wrong flag to deduct points from the player"""
    name = "wrong"
    templates = {  # Handlebars templates used for flag editing & viewing
        'create': '/plugins/CTFd-multi-answer/assets/create-wrong-modal.njk',
        'update': '/plugins/CTFd-multi-answer/assets/edit-wrong-modal.njk',
    }

    @staticmethod
    def compare(saved, provided):
        """Compare the saved and provided flags"""
        if len(saved) != len(provided):
            return False
        result = 0
        for x, y in zip(saved, provided):
            result |= ord(x) ^ ord(y)
        return result == 0


class CTFdCorrectFlag(BaseFlag):
    """Wrong key to deduct points from the player"""
    name = "correct"
    templates = {  # Handlebars templates used for key editing & viewing
        'create': '/plugins/CTFd-multi-answer/assets/create-correct-modal.njk',
        'update': '/plugins/CTFd-multi-answer/assets/edit-correct-modal.njk',
    }

    @staticmethod
    def compare(saved, provided):
        """Compare the saved and provided flags"""
        if len(saved) != len(provided):
            return False
        result = 0
        for x, y in zip(saved, provided):
            result |= ord(x) ^ ord(y)
        return result == 0


def load(app):
    """load overrides for multianswer plugin to work properly"""
    app.db.create_all()
    register_plugin_assets_directory(app, base_path='/plugins/CTFd-multi-answer/assets/')
    CHALLENGE_CLASSES["multianswer"] = CTFdMultiAnswerChallenge
    FLAG_CLASSES["wrong"] = CTFdWrongFlag
    FLAG_CLASSES["correct"] = CTFdCorrectFlag
