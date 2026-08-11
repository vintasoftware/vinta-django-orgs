from collections.abc import Callable
from functools import partial
from typing import Any

from django.contrib.auth import get_user_model
from django.db import transaction
from rest_framework import serializers

from .models import Article, Tag

UserModel = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserModel
        fields = ('id', 'first_name', 'last_name', 'email')


class TagSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tag
        fields = (
            'id',
            'text',
        )

    def create(self, validated_data: dict[str, Any]) -> Tag:
        tag = Tag.objects.filter(**validated_data).first()

        if tag:
            return tag

        return Tag.objects.create(**validated_data)


class ArticleSerializer(serializers.ModelSerializer):
    tags = TagSerializer(many=True, required=False, allow_null=True)
    author = UserSerializer(read_only=True)

    class Meta:
        model = Article
        fields = ('id', 'title', 'text', 'tags', 'author')

    def validate_tags(self, tags_dict_list: list[dict[str, Any]]) -> list[Callable[[], Tag]]:
        tags_creators: list[Callable[[], Tag]] = []
        has_errors = False
        errors: list[Any] = []
        for tag_dict in tags_dict_list:
            if not tag_dict.get('id'):
                serializer = TagSerializer(data=tag_dict)
            else:
                instance = Tag.objects.get(id=tag_dict.get('id'))
                serializer = TagSerializer(instance, data=tag_dict)

            if serializer.is_valid():
                # ``partial`` rather than a lambda with a default argument:
                # both bind this iteration's serializer instead of the loop
                # variable, and this one has a type the checker can read.
                tags_creators.append(partial(serializer.save))
                errors.append({})
            else:
                has_errors = True
                errors.append(serializer.errors)

        if has_errors:
            raise serializers.ValidationError(errors)

        return tags_creators

    def create(self, validated_data: dict[str, Any]) -> Article:
        tag_creators = validated_data.pop('tags', [])
        create_data = dict(validated_data, **{'author': self.context['request'].user})
        with transaction.atomic():
            tags = [tag_creator() for tag_creator in tag_creators]
            article = super().create(create_data)
            article.tags.set(tags)
            return article

    def update(self, instance: Article, validated_data: dict[str, Any]) -> Article:
        tag_creators = validated_data.pop('tags', [])
        create_data = dict(validated_data, **{'author': self.context['request'].user})

        with transaction.atomic():
            tags = [tag_creator() for tag_creator in tag_creators]
            # ``Options.get_all_field_names()`` was removed in Django 1.10;
            # this is the replacement the release notes give for it.
            for field_name in [f.name for f in Article._meta.get_fields()]:
                setattr(instance, field_name, create_data.get(field_name, getattr(instance, field_name)))

            instance.tags.set(tags)
            return instance
