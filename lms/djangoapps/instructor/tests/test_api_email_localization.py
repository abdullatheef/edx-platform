# -*- coding: utf-8 -*-
"""
Unit tests for the localization of emails sent by instructor.api methods.
"""

from django.core import mail
from django.core.urlresolvers import reverse
from django.test import TestCase

from courseware.tests.factories import InstructorFactory
from lang_pref import LANGUAGE_KEY
from student.models import CourseEnrollment
from student.tests.factories import UserFactory
from openedx.core.djangoapps.user_api.models import UserPreference
from xmodule.modulestore.tests.factories import CourseFactory


class TestInstructorAPIEnrollmentEmailLocalization(TestCase):
    """
    Test whether the enroll, unenroll and beta role emails are sent in the
    proper language, i.e: the student's language.
    """

    def setUp(self):
        # Platform language is English, instructor's language is Chinese,
        # student's language is French, so the emails should all be sent in
        # French.
        self.course = CourseFactory.create()
        self.instructor = InstructorFactory(course_key=self.course.id)
        UserPreference.set_preference(self.instructor, LANGUAGE_KEY, 'zh-cn')
        self.client.login(username=self.instructor.username, password='test')

        self.student = UserFactory.create()
        UserPreference.set_preference(self.student, LANGUAGE_KEY, 'fr')

    def update_enrollement(self, action, student_email):
        """
        Update the current student enrollment status.
        """
        url = reverse('students_update_enrollment', kwargs={'course_id': self.course.id.to_deprecated_string()})
        args = {'identifiers': student_email, 'email_students': 'true', 'action': action}
        response = self.client.post(url, args)
        return response

    def check_outbox_is_french(self):
        """
        Check that the email outbox contains exactly one message for which both
        the message subject and body contain a certain French string.
        """
        return self.check_outbox(u"Vous avez été")

    def check_outbox(self, expected_message):
        """
        Check that the email outbox contains exactly one message for which both
        the message subject and body contain a certain string.
        """
        self.assertEqual(1, len(mail.outbox))
        self.assertIn(expected_message, mail.outbox[0].subject)
        self.assertIn(expected_message, mail.outbox[0].body)

    def test_enroll(self):
        self.update_enrollement("enroll", self.student.email)

        self.check_outbox_is_french()

    def test_unenroll(self):
        CourseEnrollment.enroll(
            self.student,
            self.course.id
        )
        self.update_enrollement("unenroll", self.student.email)

        self.check_outbox_is_french()

    def test_set_beta_role(self):
        url = reverse('bulk_beta_modify_access', kwargs={'course_id': self.course.id.to_deprecated_string()})
        self.client.post(url, {'identifiers': self.student.email, 'action': 'add', 'email_students': 'true'})

        self.check_outbox_is_french()

    def test_enroll_unsubscribed_student(self):
        # Student is unknown, so the platform language should be used
        self.update_enrollement("enroll", "newuser@hotmail.com")
        self.check_outbox("You have been")
