"""
Tests for user enrollment.
"""
import ddt
import json
import unittest

from mock import patch
from django.test.utils import override_settings
from django.core.urlresolvers import reverse
from rest_framework.test import APITestCase
from rest_framework import status
from django.conf import settings
from xmodule.modulestore.tests.django_utils import (
    ModuleStoreTestCase, mixed_store_config
)
from xmodule.modulestore.tests.factories import CourseFactory
from enrollment import api
from enrollment.errors import CourseEnrollmentError
from student.tests.factories import UserFactory, CourseModeFactory
from student.models import CourseEnrollment

# Since we don't need any XML course fixtures, use a modulestore configuration
# that disables the XML modulestore.
MODULESTORE_CONFIG = mixed_store_config(settings.COMMON_TEST_DATA_ROOT, {}, include_xml=False)


@ddt.ddt
@override_settings(MODULESTORE=MODULESTORE_CONFIG)
@unittest.skipUnless(settings.ROOT_URLCONF == 'lms.urls', 'Test only valid in lms')
class EnrollmentTest(ModuleStoreTestCase, APITestCase):
    """
    Test user enrollment, especially with different course modes.
    """
    USERNAME = "Bob"
    EMAIL = "bob@example.com"
    PASSWORD = "edx"

    def setUp(self):
        """ Create a course and user, then log in. """
        super(EnrollmentTest, self).setUp()
        self.course = CourseFactory.create()
        self.user = UserFactory.create(username=self.USERNAME, email=self.EMAIL, password=self.PASSWORD)
        self.client.login(username=self.USERNAME, password=self.PASSWORD)

    @ddt.data(
        # Default (no course modes in the database)
        # Expect that users are automatically enrolled as "honor".
        ([], 'honor'),

        # Audit / Verified / Honor
        # We should always go to the "choose your course" page.
        # We should also be enrolled as "honor" by default.
        (['honor', 'verified', 'audit'], 'honor'),
    )
    @ddt.unpack
    def test_enroll(self, course_modes, enrollment_mode):
        # Create the course modes (if any) required for this test case
        for mode_slug in course_modes:
            CourseModeFactory.create(
                course_id=self.course.id,
                mode_slug=mode_slug,
                mode_display_name=mode_slug,
            )

        # Create an enrollment
        self._create_enrollment()

        self.assertTrue(CourseEnrollment.is_enrolled(self.user, self.course.id))
        course_mode, is_active = CourseEnrollment.enrollment_mode_for_user(self.user, self.course.id)
        self.assertTrue(is_active)
        self.assertEqual(course_mode, enrollment_mode)

    def test_check_enrollment(self):
        CourseModeFactory.create(
            course_id=self.course.id,
            mode_slug='honor',
            mode_display_name='Honor',
        )
        # Create an enrollment
        self._create_enrollment()
        resp = self.client.get(
            reverse('courseenrollment', kwargs={"user": self.user.username, "course_id": unicode(self.course.id)})
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        data = json.loads(resp.content)
        self.assertEqual(unicode(self.course.id), data['course_details']['course_id'])
        self.assertEqual('honor', data['mode'])
        self.assertTrue(data['is_active'])

    def test_enroll_prof_ed(self):
        # Create the prod ed mode.
        CourseModeFactory.create(
            course_id=self.course.id,
            mode_slug='professional',
            mode_display_name='Professional Education',
        )

        # Enroll in the course, this will fail if the mode is not explicitly professional.
        resp = self._create_enrollment(expected_status=status.HTTP_400_BAD_REQUEST)

        # While the enrollment wrong is invalid, the response content should have
        # all the valid enrollment modes.
        data = json.loads(resp.content)
        self.assertEqual(unicode(self.course.id), data['course_details']['course_id'])
        self.assertEqual(1, len(data['course_details']['course_modes']))
        self.assertEqual('professional', data['course_details']['course_modes'][0]['slug'])

    def test_user_not_specified(self):
        CourseModeFactory.create(
            course_id=self.course.id,
            mode_slug='honor',
            mode_display_name='Honor',
        )
        # Create an enrollment
        self._create_enrollment()
        resp = self.client.get(
            reverse('courseenrollment', kwargs={"course_id": unicode(self.course.id)})
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        data = json.loads(resp.content)
        self.assertEqual(unicode(self.course.id), data['course_details']['course_id'])
        self.assertEqual('honor', data['mode'])
        self.assertTrue(data['is_active'])

    def test_user_not_authenticated(self):
        # Log out, so we're no longer authenticated
        self.client.logout()

        # Try to enroll, this should fail.
        self._create_enrollment(expected_status=status.HTTP_403_FORBIDDEN)

    def test_user_not_activated(self):
        # Log out the default user, Bob.
        self.client.logout()

        # Create a user account
        self.user = UserFactory.create(
            username="inactive",
            email="inactive@example.com",
            password=self.PASSWORD,
            is_active=True
        )

        # Log in with the unactivated account
        self.client.login(username="inactive", password=self.PASSWORD)

        # Deactivate the user. Has to be done after login to get the user into the
        # request and properly logged in.
        self.user.is_active = False
        self.user.save()

        # Enrollment should succeed, even though we haven't authenticated.
        self._create_enrollment()

    def test_user_does_not_match_url(self):
        # Try to enroll a user that is not the authenticated user.
        CourseModeFactory.create(
            course_id=self.course.id,
            mode_slug='honor',
            mode_display_name='Honor',
        )
        self._create_enrollment(username='not_the_user', expected_status=status.HTTP_404_NOT_FOUND)

    def test_user_does_not_match_param_for_list(self):
        CourseModeFactory.create(
            course_id=self.course.id,
            mode_slug='honor',
            mode_display_name='Honor',
        )
        resp = self.client.get(reverse('courseenrollments'), {"user": "not_the_user"})
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_user_does_not_match_param(self):
        CourseModeFactory.create(
            course_id=self.course.id,
            mode_slug='honor',
            mode_display_name='Honor',
        )
        resp = self.client.get(
            reverse('courseenrollment', kwargs={"user": "not_the_user", "course_id": unicode(self.course.id)})
        )
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_get_course_details(self):
        CourseModeFactory.create(
            course_id=self.course.id,
            mode_slug='honor',
            mode_display_name='Honor',
        )
        resp = self.client.get(
            reverse('courseenrollmentdetails', kwargs={"course_id": unicode(self.course.id)})
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

        data = json.loads(resp.content)
        self.assertEqual(unicode(self.course.id), data['course_id'])

    def test_with_invalid_course_id(self):
        self._create_enrollment(course_id='entirely/fake/course', expected_status=status.HTTP_400_BAD_REQUEST)

    def test_get_enrollment_details_bad_course(self):
        resp = self.client.get(
            reverse('courseenrollmentdetails', kwargs={"course_id": "some/fake/course"})
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    @patch.object(api, "get_enrollment")
    def test_get_enrollment_internal_error(self, mock_get_enrollment):
        mock_get_enrollment.side_effect = CourseEnrollmentError("Something bad happened.")
        resp = self.client.get(
            reverse('courseenrollment', kwargs={"user": self.user.username, "course_id": unicode(self.course.id)})
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def _create_enrollment(self, course_id=None, username=None, expected_status=status.HTTP_200_OK):
        course_id = unicode(self.course.id) if course_id is None else course_id
        username = self.user.username if username is None else username
        """Enroll in the course and verify the URL we are sent to. """

        resp = self.client.post(
            reverse('courseenrollments'),
            {
                'course_details': {
                    'course_id': course_id
                },
                'user': username
            },
            format='json'
        )
        self.assertEqual(resp.status_code, expected_status)

        if expected_status == status.HTTP_200_OK:
            data = json.loads(resp.content)
            self.assertEqual(course_id, data['course_details']['course_id'])
            self.assertEqual('honor', data['mode'])
            self.assertTrue(data['is_active'])
        return resp

    def test_get_enrollment_with_invalid_key(self):
        resp = self.client.post(
            reverse('courseenrollments'),
            {
                'course_details': {
                    'course_id': 'invalidcourse'
                },
                'user': self.user.username
            },
            format='json'
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("No course ", resp.content)
