''' test for app action functionality '''
from unittest.mock import patch
from django.test import TestCase
from django.test.client import RequestFactory

from bookwyrm import models, views


class InteractionViews(TestCase):
    ''' viewing and creating statuses '''
    def setUp(self):
        ''' we need basic test data and mocks '''
        self.factory = RequestFactory()
        self.local_user = models.User.objects.create_user(
            'mouse@local.com', 'mouse@mouse.com', 'mouseword',
            local=True, localname='mouse',
            remote_id='https://example.com/users/mouse',
        )
        with patch('bookwyrm.models.user.set_remote_server'):
            self.remote_user = models.User.objects.create_user(
                'rat', 'rat@email.com', 'ratword',
                local=False,
                remote_id='https://example.com/users/rat',
                inbox='https://example.com/users/rat/inbox',
                outbox='https://example.com/users/rat/outbox',
            )

        work = models.Work.objects.create(title='Test Work')
        self.book = models.Edition.objects.create(
            title='Example Edition',
            remote_id='https://example.com/book/1',
            parent_work=work
        )


    def test_handle_favorite(self):
        ''' create and broadcast faving a status '''
        view = views.Favorite.as_view()
        request = self.factory.post('')
        request.user = self.remote_user
        status = models.Status.objects.create(
            user=self.local_user, content='hi')

        with patch('bookwyrm.broadcast.broadcast_task.delay'):
            view(request, status.id)
        fav = models.Favorite.objects.get()
        self.assertEqual(fav.status, status)
        self.assertEqual(fav.user, self.remote_user)

        notification = models.Notification.objects.get()
        self.assertEqual(notification.notification_type, 'FAVORITE')
        self.assertEqual(notification.user, self.local_user)
        self.assertEqual(notification.related_user, self.remote_user)


    def test_handle_unfavorite(self):
        ''' unfav a status '''
        view = views.Unfavorite.as_view()
        request = self.factory.post('')
        request.user = self.remote_user
        status = models.Status.objects.create(
            user=self.local_user, content='hi')
        with patch('bookwyrm.broadcast.broadcast_task.delay'):
            views.Favorite.as_view()(request, status.id)

        self.assertEqual(models.Favorite.objects.count(), 1)
        self.assertEqual(models.Notification.objects.count(), 1)

        with patch('bookwyrm.broadcast.broadcast_task.delay'):
            view(request, status.id)
        self.assertEqual(models.Favorite.objects.count(), 0)
        self.assertEqual(models.Notification.objects.count(), 0)


    def test_handle_boost(self):
        ''' boost a status '''
        view = views.Boost.as_view()
        request = self.factory.post('')
        request.user = self.remote_user
        status = models.Status.objects.create(
            user=self.local_user, content='hi')

        with patch('bookwyrm.broadcast.broadcast_task.delay'):
            view(request, status.id)

        boost = models.Boost.objects.get()
        self.assertEqual(boost.boosted_status, status)
        self.assertEqual(boost.user, self.remote_user)
        self.assertEqual(boost.privacy, 'public')

        notification = models.Notification.objects.get()
        self.assertEqual(notification.notification_type, 'BOOST')
        self.assertEqual(notification.user, self.local_user)
        self.assertEqual(notification.related_user, self.remote_user)
        self.assertEqual(notification.related_status, status)

    def test_handle_boost_unlisted(self):
        ''' boost a status '''
        view = views.Boost.as_view()
        request = self.factory.post('')
        request.user = self.local_user
        status = models.Status.objects.create(
            user=self.local_user, content='hi', privacy='unlisted')

        with patch('bookwyrm.broadcast.broadcast_task.delay'):
            view(request, status.id)

        boost = models.Boost.objects.get()
        self.assertEqual(boost.privacy, 'unlisted')

    def test_handle_boost_private(self):
        ''' boost a status '''
        view = views.Boost.as_view()
        request = self.factory.post('')
        request.user = self.local_user
        status = models.Status.objects.create(
            user=self.local_user, content='hi', privacy='followers')

        with patch('bookwyrm.broadcast.broadcast_task.delay'):
            view(request, status.id)
        self.assertFalse(models.Boost.objects.exists())

    def test_handle_boost_twice(self):
        ''' boost a status '''
        view = views.Boost.as_view()
        request = self.factory.post('')
        request.user = self.local_user
        status = models.Status.objects.create(
            user=self.local_user, content='hi')

        with patch('bookwyrm.broadcast.broadcast_task.delay'):
            view(request, status.id)
            view(request, status.id)
        self.assertEqual(models.Boost.objects.count(), 1)


    def test_handle_unboost(self):
        ''' undo a boost '''
        view = views.Unboost.as_view()
        request = self.factory.post('')
        request.user = self.remote_user
        status = models.Status.objects.create(
            user=self.local_user, content='hi')
        with patch('bookwyrm.broadcast.broadcast_task.delay'):
            views.Boost.as_view()(request, status.id)

        self.assertEqual(models.Boost.objects.count(), 1)
        self.assertEqual(models.Notification.objects.count(), 1)
        with patch('bookwyrm.broadcast.broadcast_task.delay'):
            view(request, status.id)
        self.assertEqual(models.Boost.objects.count(), 0)
        self.assertEqual(models.Notification.objects.count(), 0)
