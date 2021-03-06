''' handle reading a csv from goodreads '''
import csv
import logging

from bookwyrm import models
from bookwyrm.broadcast import broadcast
from bookwyrm.models import ImportJob, ImportItem
from bookwyrm.status import create_notification
from bookwyrm.tasks import app

logger = logging.getLogger(__name__)


def create_job(user, csv_file, include_reviews, privacy):
    ''' check over a csv and creates a database entry for the job'''
    job = ImportJob.objects.create(
        user=user,
        include_reviews=include_reviews,
        privacy=privacy
    )
    for index, entry in enumerate(list(csv.DictReader(csv_file))):
        if not all(x in entry for x in ('ISBN13', 'Title', 'Author')):
            raise ValueError('Author, title, and isbn must be in data.')
        ImportItem(job=job, index=index, data=entry).save()
    return job


def create_retry_job(user, original_job, items):
    ''' retry items that didn't import '''
    job = ImportJob.objects.create(
        user=user,
        include_reviews=original_job.include_reviews,
        privacy=original_job.privacy,
        retry=True
    )
    for item in items:
        ImportItem(job=job, index=item.index, data=item.data).save()
    return job


def start_import(job):
    ''' initalizes a csv import job '''
    result = import_data.delay(job.id)
    job.task_id = result.id
    job.save()


@app.task
def import_data(job_id):
    ''' does the actual lookup work in a celery task '''
    job = ImportJob.objects.get(id=job_id)
    try:
        for item in job.items.all():
            try:
                item.resolve()
            except Exception as e:# pylint: disable=broad-except
                logger.exception(e)
                item.fail_reason = 'Error loading book'
                item.save()
                continue

            if item.book:
                item.save()

                # shelves book and handles reviews
                handle_imported_book(
                    job.user, item, job.include_reviews, job.privacy)
            else:
                item.fail_reason = 'Could not find a match for book'
                item.save()
    finally:
        create_notification(job.user, 'IMPORT', related_import=job)
        job.complete = True
        job.save()


def handle_imported_book(user, item, include_reviews, privacy):
    ''' process a goodreads csv and then post about it '''
    if isinstance(item.book, models.Work):
        item.book = item.book.default_edition
    if not item.book:
        return

    existing_shelf = models.ShelfBook.objects.filter(
        book=item.book, added_by=user).exists()

    # shelve the book if it hasn't been shelved already
    if item.shelf and not existing_shelf:
        desired_shelf = models.Shelf.objects.get(
            identifier=item.shelf,
            user=user
        )
        shelf_book = models.ShelfBook.objects.create(
            book=item.book, shelf=desired_shelf, added_by=user)
        broadcast(user, shelf_book.to_add_activity(user), privacy=privacy)

    for read in item.reads:
        # check for an existing readthrough with the same dates
        if models.ReadThrough.objects.filter(
                user=user, book=item.book,
                start_date=read.start_date,
                finish_date=read.finish_date
            ).exists():
            continue
        read.book = item.book
        read.user = user
        read.save()

    if include_reviews and (item.rating or item.review):
        review_title = 'Review of {!r} on Goodreads'.format(
            item.book.title,
        ) if item.review else ''

        # we don't know the publication date of the review,
        # but "now" is a bad guess
        published_date_guess = item.date_read or item.date_added
        review = models.Review.objects.create(
            user=user,
            book=item.book,
            name=review_title,
            content=item.review,
            rating=item.rating,
            published_date=published_date_guess,
            privacy=privacy,
        )
        # we don't need to send out pure activities because non-bookwyrm
        # instances don't need this data
        broadcast(user, review.to_create_activity(user), privacy=privacy)
