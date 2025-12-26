from django.views.generic import ListView, CreateView
from django.views.generic import UpdateView, DeleteView, DetailView
from django.shortcuts import get_object_or_404, redirect
from django.http import Http404
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.models import User
from django.utils import timezone
from django.core.exceptions import PermissionDenied
from django.db.models import Count
from django.urls import reverse_lazy, reverse


from .forms import CommentForm, PostForm, UserProfileForm
from .models import Post, Category, Comment


class PostListView(ListView):
    """
    Представление для отображения списка опубликованных постов.
    
    Отображает все посты, которые соответствуют критериям публикации:
    - Пост опубликован (is_published=True)
    - Дата публикации меньше или равна текущей дате
    - Категория поста опубликована
    
    Особенности:
    - Пагинация: 10 постов на странице
    - Аннотация: подсчет количества комментариев для каждого поста
    - Оптимизация запросов: select_related для author, prefetch_related для category и location
    - Сортировка: по убыванию даты публикации (новые первыми)
    """
    model = Post
    paginate_by = 10
    template_name = 'blog/index.html'

    def get_queryset(self):
        queryset = Post.objects.filter(
            is_published=True,
            pub_date__lte=timezone.now(),
            category__is_published=True
        ).select_related('author').prefetch_related(
            'category', 'location').order_by('-pub_date').annotate(
                comment_count=Count('comments')
        )

        return queryset


class PostCreateView(LoginRequiredMixin, CreateView):
    """
    Представление для создания нового поста.
    
    Доступно только авторизованным пользователям.
    Автоматически назначает автором текущего пользователя.
    
    Требует аутентификации:
    - Неавторизованные пользователи перенаправляются на страницу входа
    
    После успешного создания поста перенаправляет на профиль автора.
    """
    model = Post
    form_class = PostForm
    template_name = 'blog/create.html'
    login_url = '/login/'

    def form_valid(self, form):
        form.instance.author = self.request.user
        return super().form_valid(form)

    def get_success_url(self):
        username = self.object.author.username
        return reverse('blog:profile', args=[username])


class PostUpdateView(UpdateView):
    """
    Представление для редактирования существующего поста.
    
    Доступно только автору поста. Проверяет права доступа через test_func.
    Неавторизованные пользователи или пользователи, не являющиеся авторами,
    перенаправляются на страницу детального просмотра поста.
    
    После успешного обновления перенаправляет на страницу поста.
    """
    model = Post
    form_class = PostForm
    template_name = 'blog/create.html'

    def test_func(self):
        self.object = self.get_object()
        return (
            self.request.user.is_authenticated
            and self.object.author == self.request.user
        )

    def dispatch(self, request, *args, **kwargs):
        if not self.test_func():
            return redirect(reverse(
                'blog:post_detail', kwargs={'post_id': self.kwargs['pk']}
            ))
        else:
            return super().dispatch(request, *args, **kwargs)

    def get_success_url(self):
        return reverse_lazy(
            'blog:post_detail', kwargs={'post_id': self.object.pk}
        )


class PostDeleteView(LoginRequiredMixin, DeleteView):
    """
    Представление для удаления поста.
    
    Доступно только авторизованным пользователям.
    Фильтрует queryset так, чтобы пользователь мог удалять только свои посты.
    
    После успешного удаления перенаправляет на главную страницу.
    """
    model = Post
    template_name = 'blog/create.html'
    success_url = reverse_lazy('blog:index')
    pk_url_kwarg = 'post_id'

    def get_queryset(self):
        qs = super().get_queryset()
        return qs.filter(author=self.request.user)


class PostDetailView(DetailView):
    """
    Представление для детального просмотра поста.
    
    Отображает полную информацию о посте с учетом правил видимости:
    - Пост доступен автору всегда
    - Для других пользователей пост доступен только если:
        1. Пост опубликован
        2. Категория поста опубликована
        3. Дата публикации наступила
    
    В контексте также передаются все комментарии к посту и форма для добавления нового комментария.
    """
    model = Post
    template_name = 'blog/detail.html'

    def get_object(self, queryset=None):
        post_id = self.kwargs.get('post_id')
        post = get_object_or_404(Post, id=post_id)
        if (
            post.author == self.request.user
            or (post.is_published and post.category.is_published
                and post.pub_date <= timezone.now())
        ):

            return post
        raise Http404('Страница не найдена')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        post = self.get_object()
        comments = post.comments.all().order_by('created_at')
        context['form'] = CommentForm()
        context['comments'] = comments

        return context


class ProfileView(ListView):
    """
    Представление для отображения профиля пользователя.
    
    Отображает все посты указанного пользователя, независимо от их статуса публикации.
    Включает информацию о пользователе и аннотирует посты количеством комментариев.
    
    Пагинация: 10 постов на странице.
    """
    model = Post
    template_name = 'blog/profile.html'
    paginate_by = 10

    def get_queryset(self):
        username = self.kwargs['username']
        profile = get_object_or_404(User, username=username)
        posts = Post.objects.filter(author=profile).select_related(
            'author').prefetch_related('comments', 'category', 'location')
        posts_annotated = posts.annotate(comment_count=Count('comments'))
        return posts_annotated.order_by('-pub_date')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if 'profile' not in context:
            context['profile'] = get_object_or_404(
                User, username=self.kwargs['username'])
        return context


class CategoryPostsView(ListView):
    """
    Представление для отображения постов определенной категории.
    
    Отображает только опубликованные посты в опубликованной категории.
    Категория определяется по slug в URL.
    
    Особенности:
    - Отображает только посты с датой публикации не позже текущей
    - Аннотирует посты количеством комментариев
    - Пагинация: 10 постов на странице
    - В контексте передается объект категории
    """
    model = Post
    paginate_by = 10
    template_name = 'blog/category.html'

    def get_queryset(self):
        self.category = get_object_or_404(
            Category, slug=self.kwargs['category_slug'], is_published=True
        )

        queryset = Post.objects.filter(
            is_published=True,
            pub_date__lte=timezone.now(),
            category=self.category
        ).select_related('author',
                         'category',
                         'location').order_by('-pub_date')

        queryset = queryset.annotate(comment_count=Count('comments'))
        queryset = queryset.filter(category__is_published=True)

        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['category'] = self.category
        return context


class EditProfileView(LoginRequiredMixin, UpdateView):
    """
    Представление для редактирования профиля пользователя.
    
    Доступно только авторизованным пользователям.
    Позволяет пользователю редактировать свои данные профиля.
    
    После успешного обновления перенаправляет на страницу профиля.
    """
    model = User
    form_class = UserProfileForm
    template_name = 'blog/user.html'

    def get_success_url(self):
        return reverse_lazy(
            'blog:profile', kwargs={'username': self.object.username}
        )

    def get_object(self):
        return self.request.user


class AddCommentView(LoginRequiredMixin, CreateView):
    """
    Представление для добавления комментария к посту.
    
    Доступно только авторизованным пользователям.
    Автоматически связывает комментарий с постом и текущим пользователем как автором.
    
    После успешного создания комментария перенаправляет на страницу поста.
    """
    model = Comment
    form_class = CommentForm
    template_name = 'comments.html'

    def get_success_url(self):
        post_id = self.kwargs.get('post_id')
        return reverse('blog:post_detail', kwargs={'post_id': post_id})

    def form_valid(self, form):
        post_id = self.kwargs.get('post_id')
        post = get_object_or_404(Post, id=post_id)
        form.instance.post = post
        form.instance.author = self.request.user
        return super().form_valid(form)


class EditCommentView(LoginRequiredMixin, UpdateView):
    """
    Представление для редактирования существующего комментария.
    
    Доступно только автору комментария.
    Проверяет права доступа: если пользователь не является автором, вызывает PermissionDenied.
    
    После успешного редактирования перенаправляет на главную страницу.
    """
    model = Comment
    form_class = CommentForm
    template_name = 'blog/comment.html'
    success_url = reverse_lazy('blog:index')

    def dispatch(self, request, *args, **kwargs):
        self.object = self.get_object()
        if self.object.author != request.user:
            raise PermissionDenied(
                'Вы не авторизованы для редактирования этого комментария.'
            )
        return super().dispatch(request, *args, **kwargs)

    def get_object(self, queryset=None):
        comment_id = self.kwargs.get('comment_id')
        return get_object_or_404(Comment, id=comment_id)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['post_id'] = self.kwargs.get('post_id')
        return context


class DeleteCommentView(LoginRequiredMixin, DeleteView):
    """
    Представление для удаления комментария.
    
    Доступно только автору комментария.
    Проверяет права доступа: если пользователь не является автором, вызывает PermissionDenied.
    
    После успешного удаления перенаправляет на страницу поста, к которому относился комментарий.
    """
    model = Comment
    template_name = 'blog/comment.html'
    pk_url_kwarg = 'comment_id'

    def dispatch(self, request, *args, **kwargs):
        self.object = self.get_object()
        if self.object.author != request.user:
            raise PermissionDenied(
                'Вы не авторизованы для удаления этого комментария.'
            )
        return super().dispatch(request, *args, **kwargs)

    def get_success_url(self):
        post_id = self.kwargs.get('post_id')
        return reverse_lazy('blog:post_detail', kwargs={'post_id': post_id})

    def post(self, request, *args, **kwargs):
        return self.delete(request, *args, **kwargs)
    