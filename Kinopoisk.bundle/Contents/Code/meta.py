# -*- coding: utf-8 -*-
import const, scoring, translit
import guessit, urllib2, re
from qtparse import QtParser
from jpgparser import JpegImageFile

def make_request(url, headerlist={'Accept': 'application/json'}, cache_time=CACHE_1MONTH):
    json_data = None
    try:
        json_data = JSON.ObjectFromURL(url, sleep=2.0, headers=headerlist, cacheTime=cache_time)
        return json_data['data'] if 'data' in json_data else json_data
    except:
        pass

    return json_data

def make_kp_request(url):
    headerlist = {
        'Image-Scale': 1,
        'countryID': 2,
        'cityID': 1,
        'Content-Lang': 'ru',
        'Accept': 'application/json',
        'device': 'android',
        'Android-Api-Version': 19,
        'clientDate': Datetime.Now().strftime("%H:%M %d.%m.%Y")
    }
    json_data = make_request(url + '&key=' + Hash.MD5(url[len(const.KP_BASE_URL) + 1:] + const.KP_KEY), headerlist)
    return json_data['data'] if 'data' in json_data else json_data

# check for ascii
def is_ascii(s):
    return s.encode("ascii", "ignore").decode("ascii") == s

# check for digits
def contains_digits(d):
    return bool(const.RE_digits.search(d))

# check for chinese/jap
def is_chinese_cjk(s):
    return bool(const.RE_JAP.search(s))


class KPMeta:
    def __init__(self, type):
        self.is_primary = True
        self.type = type

    def check_entry(self, entry):
        if {'id', 'nameRU', 'year'} <= set(entry) and entry['type'] == 'KPFilmObject':
            if '-' not in entry['year'] and not entry['nameRU'].endswith((u'(сериал)', u'(мини-сериал)')):
                return True if self.type == 'movie' else False
            return False if self.type == 'movie' else True
        return False

    def make_search(self, result, title, year):
        # search using original name
        search_result = make_kp_request(url=const.KP_MOVIE_SEARCH % String.Quote(title, usePlus=False))
        if 'items' in search_result:
            # first filter search results
            filtred_result = [
                dict(i, year=i['year'].split('-', 1)[0]) for i in search_result['items'] if self.check_entry(i)
                ]
            # calculate score and add to result
            result.extend(
                [dict(
                    d,
                    score=scoring.score_title(d, year, title, i + 1)
                ) for i, d in enumerate(filtred_result)]
            )

    def make_trans_title(self, title, combi):
        # contains ascii - translit
        if is_ascii(title):
            if Prefs['search.use_translit'] is True:
                trans_name = translit.detranslify(title)
                # make translit
                combi.append(trans_name)
            # contains digits
            if Prefs['search.use_digits'] is True and contains_digits(title):
                # make digit2word english
                combi.append(translit.trans_digits(title, True))
                if Prefs['search.use_translit'] is True:
                    # make digit2word russian
                    combi.append(translit.trans_digits(trans_name))
        else:
            if Prefs['search.use_digits'] is True:
                # make digit2word russian
                combi.append(translit.trans_digits(title))

    def search(self, results, media, lang, manual):
        Log.Info('### Kinopoisk search start ###')
        search_combinations = []
        search_list = []
        if media.primary_agent is not None:
            Log.Info('### Kinopoisk not primary')
            self.is_primary = False
            # kinopoiskru.bundle - result match 100%
            if media.primary_agent == 'com.plexapp.agents.kinopoiskru':
                Log.Info('Get request from KinopoiskRu (id %s)', media.primary_metadata.id)
                results.Append(MetadataSearchResult(
                    id=media.primary_metadata.id,
                    score=100
                ))
                return  # nothing to do here
            # other bundle - search by title
            else:
                search_combinations.append(media.primary_metadata.title)
                search_combinations.append(media.primary_metadata.original_title)
        else:
            if self.type == 'movie':
                media_name = unicode(re.sub(r'\[.*?\]', '', media.name)).lower()
            else:
                media_name = unicode(re.sub(r'\[.*?\]', '', media.show)).lower()
            self.is_primary = False

            if media.year is None:
                year_match = const.RE_YEAR.search(media_name)
                if year_match:
                    year_str = year_match.group(1)
                    year_int = int(year_str)
                    if 1900 < year_int < (Datetime.Now().year + 1) and year_str != media_name:
                        media.year = year_int
                        media_name = media_name.replace(year_str, '')

            search_combinations.append(media_name)
            self.make_trans_title(media_name, search_combinations)

            if Prefs['search.parse_filename'] is True:
                file_info = {}
                try:
                    file_info = guessit.guess_movie_info(String.Unquote(media.filename))
                    Log.Info('### guessit start')
                    if 'title' in file_info and file_info['title'].lower() != media_name:
                        search_combinations.append(file_info['title'])
                        self.make_trans_title(file_info['title'], search_combinations)
                    if 'year' in file_info and media.year is None:
                        media.year = int(file_info['year'])
                except:
                    Log.Info('guessit exception raised. Skipping...')

            search_combinations = list(set(word.lower().strip() for word in search_combinations))

        @parallelize
        def do_search():
            for s in search_combinations:
                Log.Debug('### SEARCH ### Quering %s', s)

                @task
                def score_search(s=s, search_list=search_list, year=media.year):
                    result = []
                    self.make_search(result, s, year)
                    if result:
                        search_list.extend(result)

        res = {}
        for di in sorted(search_list, key=lambda d: d['score']):
            res[di['id']] = di
        search_list = res.values()

        for entry in search_list:
            if Prefs['search.show_zero'] is True or entry['score'] > 0:
                results.Append(
                    MetadataSearchResult(
                        id=entry['id'],
                        name=entry['nameRU'],
                        year=str(entry['year']),
                        lang=lang,
                        score=entry['score'],
                        thumb='test124'
                    )
                )

        results.Sort('score', descending=True)

    def update(self, metadata, media, lang, force=False):
        Log.Info('### Kinopoisk update start ###')
        film_dict = make_kp_request(url=const.KP_MOVIE % metadata.id)
        if not isinstance(film_dict, dict):
            return None

        # title
        repls = (u' (видео)', u' (ТВ)', u' (мини-сериал)', u' (сериал)')  # remove unnecessary text
        metadata.title = reduce(lambda a, kv: a.replace(kv, ''), repls, film_dict['nameRU'])
        # original title
        if 'nameEN' in film_dict and film_dict['nameEN'] != film_dict['nameRU']:
            metadata.original_title = film_dict['nameEN']

        # countries
        metadata.countries.clear()
        if 'country' in film_dict:
            for country in film_dict['country'].split(', '):
                metadata.countries.add(country)
        # genres
        metadata.genres.clear()
        for genre in film_dict['genre'].split(', '):
            metadata.genres.add(genre.strip().title())
        # content_rating
        metadata.content_rating = film_dict.get('ratingMPAA', '')
        # originally available
        metadata.originally_available_at = Datetime.ParseDate(
            # use world premiere date, or russian premiere
            film_dict['rentData'].get('premiereWorld') or film_dict['rentData'].get('premiereRU')
        ).date() if (('rentData' in film_dict) and
                     [i for i in {'premiereWorld', 'premiereRU'} if i in film_dict['rentData']]
                     ) else None

        # summary
        summary_add = ''
        if 'ratingData' in film_dict and Prefs['data.rating_desc'] is True:
            if 'rating' in film_dict['ratingData']:
                metadata.rating = float(film_dict['ratingData'].get('rating'))
                summary_add = u'КиноПоиск: ' + film_dict['ratingData'].get('rating').__str__()
                if 'ratingVoteCount' in film_dict['ratingData']:
                    summary_add += ' (' + film_dict['ratingData'].get('ratingVoteCount').__str__() + ')'
                summary_add += '. '

            if 'ratingIMDb' in film_dict['ratingData']:
                summary_add += u'IMDb: ' + film_dict['ratingData'].get('ratingIMDb').__str__()
                if 'ratingIMDbVoteCount' in film_dict['ratingData']:
                    summary_add += ' (' + film_dict['ratingData'].get('ratingIMDbVoteCount').__str__() + ')'
                summary_add += '. '

        if summary_add != '':
            summary_add += '\n'
        metadata.summary = summary_add + film_dict.get('description', '')

        #people
        self.load_staff(metadata)

        if self.type == 'movie':
            # slogan
            metadata.tagline = film_dict.get('slogan', '')
            # content rating age
            metadata.content_rating_age = int(film_dict.get('ratingAgeLimits') or 0)
            # year
            metadata.year = int(film_dict.get('year') or 0)

    def load_staff(self, metadata):
        staff_dict = make_kp_request(url=const.KP_MOVIE_STAFF % metadata.id)
        if self.type == 'movie':
            metadata.directors.clear()
            metadata.writers.clear()
            metadata.producers.clear()
        metadata.roles.clear()
        for staff_type in staff_dict['creators']:
            for staff in staff_type:
                prole = staff.get('professionKey')
                pname = staff.get('nameRU') if len(staff.get('nameRU')) > 0 else staff.get('nameEN')
                if pname:
                    if prole == 'actor':
                        role = metadata.roles.new()
                        if hasattr(role, 'actor'):
                           role.actor = pname
                        else:
                           role.name = pname
                        if 'posterURL' in staff:
                            role.photo = const.KP_ACTOR_IMAGE % staff['id']
                        role.role = staff.get('description')
                    elif prole == 'director' and self.type == 'movie':
                        director = metadata.directors.new()
                        director.name = pname
                    elif prole == 'writer' and self.type == 'movie':
                        writer = metadata.writers.new()
                        writer.name = pname
                    elif prole == 'producer' and self.type == 'movie':
                        producer = metadata.producers.new()
                        producer.name = pname

    def load_main_poster(self, metadata, valid_poster):
        poster_url = const.KP_MAIN_POSTER % metadata.id
        preview_url = const.KP_MAIN_POSTER_THUMB % metadata.id
        req = urllib2.urlopen(poster_url, timeout=10)
        if req.geturl().endswith('no-poster.gif') is False:
            if Prefs['image.main_poster'] is True:
                sort_int = 1
            else:
                sort_int = len(valid_poster) + 1
            valid_poster.append(poster_url)
            if poster_url not in metadata.posters:
                try:
                    metadata.posters[poster_url] = Proxy.Preview(HTTP.Request(preview_url).content, sort_order=sort_int)
                except NameError, e:
                    pass

    def load_images(self, metadata, valid_art, valid_poster, lang):
        # loading image list
        images_dict = make_kp_request(url=const.KP_MOVIE_IMAGES % String.Quote(metadata.id, usePlus=False))
        # if gallery exists
        if 'gallery' in images_dict:
            if ((Prefs['image.seq'] == 'Все источники') or (len(valid_poster) < Prefs['image.max_posters'])) and \
                            'poster' in images_dict['gallery']:
                if Prefs['image.main_poster'] is True:
                    self.load_main_poster(metadata, valid_poster)
                    # load img meta in parallel
                images = []  # list of images

                @parallelize
                def LoadPosters():
                    for img in images_dict['gallery']['poster']:
                        # do load task
                        @task
                        def ScorePoster(img=img, images=images):
                            # parse jpg image file
                            jprs = JpegImageFile(const.KP_IMAGES % img['image'])
                            if jprs.quality <= 95:
                                images.append({
                                    'url': const.KP_IMAGES % img['image'],
                                    'thumb': const.KP_IMAGES % img['preview'],
                                    'size': jprs.size,
                                    'score': scoring.score_image(jprs.size, jprs.pxcount, 'poster')
                                })

                if len(images) > 0:
                    # check how many to load
                    count_to_load = int(Prefs['image.max_posters']) - len(valid_poster)
                    sort_int = len(valid_poster) + 1
                    # sort by score
                    images = sorted(images, key=lambda d: d['score'], reverse=True)
                    for i, poster in enumerate(sorted(images, key=lambda k: k['score'], reverse=True)):
                        if (Prefs['image.seq'] == 'Все источники') and i >= int(Prefs['image.max_posters']):
                            break
                        elif (Prefs['image.seq'] != 'Все источники') and i >= count_to_load:
                            break
                        else:
                            valid_poster.append(poster['url'])
                            if poster['url'] not in metadata.posters:
                                try:
                                    metadata.posters[poster['url']] = Proxy.Preview(
                                        HTTP.Request(poster['thumb']).content,
                                        sort_order=sort_int + i + 1)
                                except NameError, e:
                                    pass
            elif ((Prefs['image.seq'] == 'Все источники') or (len(valid_poster) < Prefs['image.max_posters'])) and \
                            'poster' not in images_dict['gallery']:
                self.load_main_poster(metadata, valid_poster)

            # loading art. if all sources or emty data
            if ((Prefs['image.seq'] == 'Все источники') or (len(valid_art) < Prefs['image.max_backdrops'])) and \
                            'kadr' in images_dict['gallery']:
                # load img meta in parallel
                images = []  # list of images

                @parallelize
                def LoadArts():
                    for img in images_dict['gallery']['kadr']:
                        # do load task
                        @task
                        def ScoreArt(img=img, images=images):
                            # parse jpg image file
                            jprs = JpegImageFile(const.KP_IMAGES % img['image'])
                            if jprs.quality <= 95:
                                images.append({
                                    'url': const.KP_IMAGES % img['image'],
                                    'thumb': const.KP_IMAGES % img['preview'],
                                    'size': jprs.size,
                                    'score': scoring.score_image(jprs.size, jprs.pxcount, 'art')
                                })

                if len(images) > 0:
                    count_to_load = int(Prefs['image.max_backdrops']) - len(valid_art)
                    sort_int = len(valid_art)+1
                    # sort by score
                    images = sorted(images, key=lambda d: d['score'], reverse=True)
                    for i, backdrop in enumerate(sorted(images, key=lambda k: k['score'], reverse=True)):
                        if (Prefs['image.seq'] == 'Все источники') and i >= int(Prefs['image.max_backdrops']):
                            break
                        elif (Prefs['image.seq'] != 'Все источники') and i >= count_to_load:
                            break
                        else:
                            valid_art.append(backdrop['url'])
                        if backdrop['url'] not in metadata.art:
                            try:
                                metadata.art[backdrop['url']] = Proxy.Preview(
                                    HTTP.Request(backdrop['thumb']).content,
                                    sort_order=sort_int + i + 1)
                            except NameError, e:
                                pass

        #  there is no images, but we need poster
        elif (Prefs['image.seq'] == 'Все источники') or (len(valid_poster) < Prefs['image.max_posters']):
            self.load_main_poster(metadata, valid_poster)

    def extras(self, metadata, lang):
        if (Prefs['extras.source'] == u'Все источники') or (len(metadata.extras) < Prefs['extras.max']):
            page = HTML.ElementFromURL(const.KP_TRAILERS % metadata.id, headers={
                'User-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_9_4) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/37.0.2062.120 Safari/537.36',
                'Accept': 'text/html'
            })
            if len(page) != 0:
                trailers = []  # trailers dict
                for tr in page.xpath(const.KP_EXTRA_TR):  # loop over trailers
                    tr_info = {
                        'title': tr.xpath(const.KP_EXTRA_TITLE)[0],
                        'data': [],
                        'img_id': tr.xpath(const.KP_EXTRA_IMG)[0].split('/')[-2]}

                    @parallelize
                    def load_qual():
                        for quol in tr.xpath(const.KP_EXTRA_QUAL):  # loop over quality
                            @task
                            def parse_qual(tr_info=tr_info, trailers=trailers):
                                # get trailer link. support only mp4/mov
                                tr_link = quol.xpath('.//td[3]/a/attribute::href')[0].split('link=')[-1]
                                if tr_link.split('.')[-1] in {'mp4', 'mov'}:
                                    try:
                                        qtp = QtParser()
                                        if qtp.openurl(tr_link):
                                            tr_data = qtp.analyze()
                                            tr_info['data'].append({
                                                'streams': tr_data['streams'],
                                                'audio': tr_data['audio'],
                                                'video': tr_data['video'],
                                                'bt': int(tr_data['bitrate']),
                                                'dr': int(tr_data['playtime_seconds']),
                                                'lnk': tr_link,
                                                'id': const.RE_TR_ID.search(tr_link).group(1)
                                            })
                                    except:
                                        pass
                    trailers.append(tr_info)

                trailers = sorted(trailers, key=lambda k: len(k['data']), reverse=True)

                extras = []
                count_to_load = int(Prefs['extras.max']) - len(metadata.extras)
                for i, trailer in enumerate(trailers):
                    if (Prefs['extras.seq'] == 'Все источники') and i >= int(Prefs['extras.max']):
                        break
                    elif (Prefs['extras.seq'] != 'Все источники') and i >= count_to_load:
                        break
                    else:
                        extra_type = 'trailer'
                        spoken_lang = 'ru'
                        trailer_json = JSON.StringFromObject(trailer['data'])
                        extras.append({'type': extra_type,
                                       'lang': spoken_lang,
                                       'extra': const.TYPE_MAP[extra_type](
                                           url=const.KP_TRAILERS_URL % String.Encode(trailer_json),
                                           title=trailer['title'],
                                           year=None,
                                           originally_available_at=None,
                                           thumb='http://kp.cdn.yandex.net/%s/3_%s.jpg' % (metadata.id, trailer['img_id']))})

                for extra in extras:
                    metadata.extras.add(extra['extra'])

class MDMeta:
    def __init__(self, type):
        self.type = type

    def get_ext_id(self, meta_id, type):
        if Data.Exists(meta_id):
            ids = Data.LoadObject(meta_id)
            if isinstance(ids, dict):
                return ids[type]
        return None

    def score_results(self, tmdb_dict, metadata):
        results = []
        for i, movie in enumerate(sorted(tmdb_dict['results'], key=lambda k: k['popularity'], reverse=True)):
            score = 100

            original_title_penalty = 0
            if metadata.original_title and 'original_title' in movie and is_chinese_cjk(movie['original_title']) is False:
                original_title_penalty = scoring.compute_title_penalty(metadata.original_title,
                                                                       movie['original_title'])
            #  if original title = translated title and != russian title - movie is not translated
            if movie['original_title'] == movie['title'] and movie['title'] != metadata.title:
                title_penalty = 0
            else:
                title_penalty = scoring.compute_title_penalty(metadata.title, movie['title'])
            score = score - title_penalty - original_title_penalty

            if metadata.originally_available_at and 'release_date' in movie and len(movie['release_date']) > 0:
                release_date = Datetime.ParseDate(movie['release_date']).date()
                days_diff = abs((metadata.originally_available_at - release_date).days)
                if days_diff == 0:
                    release_penalty = 0
                elif days_diff <= 10:
                    release_penalty = 5
                else:
                    release_penalty = 10
                score = score - release_penalty
                score = score - abs(metadata.originally_available_at.year - release_date.year)

            results.append({'id': movie['id'], 'title': movie['title'], 'score': score})

        results = sorted(results, key=lambda item: item['score'], reverse=True)
        if len(results) > 0:
            return results[0]
        return {}

    def make_search(self, result, metadata, title, year, lang):
        if title is not None:
            try:
                tmdb_dict = make_request(
                    url=const.TMDB_MOVIE_SEARCH % (
                        String.Quote(title.replace(":", "").encode('utf-8')),
                        year,
                        lang,
                        False
                    )
                )
                if 'total_results' in tmdb_dict and tmdb_dict['total_results'] > 0:
                    result.update(self.score_results(tmdb_dict, metadata))
            except:
                Log('Error while loading page %s', const.TMDB_MOVIE_SEARCH % (
                    String.Quote(title.replace(":", "").encode('utf-8')),
                    year,
                    lang,
                    False
                ))

    def search(self, metadata, lang):
        result_dict = []
        search_combinations = [
            {'title': metadata.title, 'year': metadata.year},
            {'title': metadata.title, 'year': ''},
            {'title': metadata.title.replace(u'ё', u'е'), 'year': metadata.year},
            {'title': metadata.title.replace(u'ё', u'е'), 'year': ''},
            {'title': metadata.original_title.replace("'s", "") if metadata.original_title else None, 'year': metadata.year},
            {'title': metadata.original_title.replace("'s", "") if metadata.original_title else None, 'year': ''}
        ]

        @parallelize
        def do_search():
            for s in search_combinations:
                @task
                def score_search(s=s, rd=result_dict):
                    result = {}
                    self.make_search(result, metadata, s['title'], s['year'], lang)
                    if result:
                        result_dict.append(result)

        res = {}
        for di in sorted(result_dict, key=lambda d: d['score']):
            res[di['id']] = di
        result_dict = res.values()

        if len(result_dict) > 0:
            # will give a chance
            if result_dict[0].get('score', 0) < 85:
                result_dict[0]['score'] = result_dict[0]['score'] + 5
            if result_dict[0].get('score', 0) >= 85:
                return result_dict[0]['id']
            return None
        return None

    def update(self, metadata, media, lang, force=False):
        if Data.Exists(metadata.id):
            tmdb_id = self.get_ext_id(metadata.id, 'tmdb')
            Log('TMDB id exists, using (%s)', tmdb_id)
        else:
            tmdb_id = self.search(metadata, lang)
            Log('No TMDB id, searching...')

        if tmdb_id is not None:
            tmdb_dict = make_request(url=const.TMDB_MOVIE % (tmdb_id, lang))
            imdb_id = tmdb_dict['imdb_id']

            if Data.Exists(metadata.id) is False:
                Data.SaveObject(metadata.id, {'tmdb': tmdb_id, 'imdb': imdb_id})

            if 'production_companies' in tmdb_dict and len(tmdb_dict['production_companies']) > 0:
                metadata.studio = tmdb_dict['production_companies'][0]['name']

            if Prefs['data.actors_eng'] is True:
                config_dict = make_request(url=const.TMDB_CONFIG, cache_time=CACHE_1WEEK * 2)
                # Crew.
                metadata.directors.clear()
                metadata.writers.clear()
                metadata.producers.clear()

                for member in tmdb_dict['credits']['crew']:
                    if member['job'] == 'Director':
                        director = metadata.directors.new()
                        director.name = member['name']
                    elif member['job'] in ('Writer', 'Screenplay'):
                        writer = metadata.writers.new()
                        writer.name = member['name']
                    elif member['job'] == 'Producer':
                        producer = metadata.producers.new()
                        producer.name = member['name']

                # Cast.
                metadata.roles.clear()

                for member in sorted(tmdb_dict['credits']['cast'], key=lambda k: k['order']):
                    role = metadata.roles.new()
                    role.role = member['character']
                    role.actor = member['name']
                    if member['profile_path'] is not None:
                        role.photo = config_dict['images']['base_url'] + 'original' + member['profile_path']

    def load_images(self, metadata, valid_art, valid_poster, lang):
        tmdb_images_dict = []
        tmdb_id = self.get_ext_id(metadata.id, 'tmdb')
        if tmdb_id is not None:
            tmdb_images_dict = make_request(url=const.TMDB_MOVIE_IMAGES % tmdb_id)
        if tmdb_images_dict:
            config_dict = make_request(url=const.TMDB_CONFIG, cache_time=CACHE_1WEEK * 2)
            if tmdb_images_dict['posters'] and \
                    ((Prefs['image.seq'] == 'Все источники') or (len(valid_poster) < Prefs['image.max_posters'])):
                max_average = max([(lambda p: float(p['vote_average']) or 5)(p) for p in tmdb_images_dict['posters']])
                max_count = max([(lambda p: float(p['vote_count']))(p) for p in tmdb_images_dict['posters']]) or 1

                for i, poster in enumerate(tmdb_images_dict['posters']):
                    score = (float(poster['vote_average']) / max_average) * const.POSTER_SCORE_RATIO
                    score += (float(poster['vote_count']) / max_count) * (1 - const.POSTER_SCORE_RATIO)
                    tmdb_images_dict['posters'][i]['score'] = score

                    # Boost the score for localized posters (according to the preference).
                    if Prefs['image.prefer_local_art']:
                        if poster['iso_639_1'] == lang:
                            tmdb_images_dict['posters'][i]['score'] = poster['score'] + 2

                        # Discount score for foreign posters.
                        if poster['iso_639_1'] != lang and poster['iso_639_1'] is not None and poster['iso_639_1'] != 'en':
                            tmdb_images_dict['posters'][i]['score'] = poster['score'] - 2

                count_to_load = int(Prefs['image.max_posters']) - len(valid_poster)
                sort_int = len(valid_poster)+1
                for i, poster in enumerate(sorted(tmdb_images_dict['posters'], key=lambda k: k['score'], reverse=True)):
                    if (Prefs['image.seq'] == 'Все источники') and i >= int(Prefs['image.max_posters']):
                        break
                    elif (Prefs['image.seq'] != 'Все источники') and i >= count_to_load:
                        break
                    else:
                        poster_url = config_dict['images']['base_url'] + 'original' + poster['file_path']
                        thumb_url = config_dict['images']['base_url'] + 'w154' + poster['file_path']
                        valid_poster.append(poster_url)

                        if poster_url not in metadata.posters:
                            try:
                                metadata.posters[poster_url] = Proxy.Preview(HTTP.Request(thumb_url).content,
                                                                             sort_order=sort_int + i + 1)
                            except NameError, e:
                                pass

            # loading art. if all sources or emty data
            if tmdb_images_dict['backdrops'] and \
                    ((Prefs['image.seq'] == 'Все источники') or (len(valid_art) < Prefs['image.max_backdrops'])):
                max_average = max([(lambda p: float(p['vote_average']) or 5)(p) for p in tmdb_images_dict['backdrops']])
                max_count = max([(lambda p: float(p['vote_count']))(p) for p in tmdb_images_dict['backdrops']]) or 1

                for i, backdrop in enumerate(tmdb_images_dict['backdrops']):
                    score = (float(backdrop['vote_average']) / max_average) * const.BACKDROP_SCORE_RATIO
                    score += (float(backdrop['vote_count']) / max_count) * (1 - const.BACKDROP_SCORE_RATIO)
                    tmdb_images_dict['backdrops'][i]['score'] = score

                    # For backdrops, we prefer "No Language" since they're intended to sit behind text.
                    if backdrop['iso_639_1'] == 'xx' or backdrop['iso_639_1'] == 'none':
                        tmdb_images_dict['backdrops'][i]['score'] = float(backdrop['score']) + 2

                    # Boost the score for localized art (according to the preference).
                    if Prefs['image.prefer_local_art']:
                        if backdrop['iso_639_1'] == lang:
                            tmdb_images_dict['backdrops'][i]['score'] = float(backdrop['score']) + 2

                        # Discount score for foreign art.
                        if backdrop['iso_639_1'] != lang and backdrop['iso_639_1'] is not None and backdrop['iso_639_1'] != 'en':
                            tmdb_images_dict['backdrops'][i]['score'] = float(backdrop['score']) - 2

                count_to_load = int(Prefs['image.max_backdrops']) - len(valid_art)
                sort_int = len(valid_art)+1
                for i, backdrop in enumerate(sorted(tmdb_images_dict['backdrops'], key=lambda k: k['score'], reverse=True)):
                    if (Prefs['image.seq'] == 'Все источники') and i >= int(Prefs['image.max_backdrops']):
                        break
                    elif (Prefs['image.seq'] != 'Все источники') and i >= count_to_load:
                        break
                    else:
                        backdrop_url = config_dict['images']['base_url'] + 'original' + backdrop['file_path']
                        thumb_url = config_dict['images']['base_url'] + 'w300' + backdrop['file_path']
                        valid_art.append(backdrop_url)

                    if backdrop_url not in metadata.art:
                        try:
                            metadata.art[backdrop_url] = Proxy.Preview(HTTP.Request(thumb_url).content,
                                                                       sort_order=sort_int + i + 1)
                        except NameError, e:
                            pass

    def extras(self, metadata, lang):
        imdb_id = self.get_ext_id(metadata.id, 'imdb')
        if imdb_id is None:
            return None
        try:
            req = const.PLEXMOVIE_EXTRAS_URL % (imdb_id[2:], lang)
            xml = XML.ElementFromURL(req)

            extras = []
            media_title = None
            for extra in xml.xpath('//extra'):
                avail = Datetime.ParseDate(extra.get('originally_available_at'))
                lang_code = int(extra.get('lang_code')) if extra.get('lang_code') else -1
                subtitle_lang_code = int(extra.get('subtitle_lang_code')) if extra.get('subtitle_lang_code') else -1

                spoken_lang = const.IVA_LANGUAGES.get(lang_code) or Locale.Language.Unknown
                subtitle_lang = const.IVA_LANGUAGES.get(subtitle_lang_code) or Locale.Language.Unknown
                include = False

                # Include extras in section language...
                if spoken_lang == lang:

                    # ...if there are no subs or english.
                    if subtitle_lang_code in {-1, Locale.Language.English}:
                        include = True

                # Include foreign language extras if they have subs in the section language.
                if spoken_lang != lang and subtitle_lang == lang:
                    include = True

                # Always include English language extras anyway (often section lang options are not available), but only if they have no subs.
                if spoken_lang == Locale.Language.English and subtitle_lang_code == -1:
                    include = True

                # Exclude non-primary trailers and scenes.
                extra_type = 'primary_trailer' if extra.get('primary') == 'true' else extra.get('type')
                if extra_type == 'trailer' or extra_type == 'scene_or_sample':
                    include = False

                if include:

                    bitrates = extra.get('bitrates') or ''
                    duration = int(extra.get('duration') or 0)

                    # Remember the title if this is the primary trailer.
                    if extra_type == 'primary_trailer':
                        media_title = extra.get('title')

                    # Add the extra.
                    if extra_type in const.TYPE_MAP:
                        extras.append({ 'type' : extra_type,
                                        'lang' : spoken_lang,
                                        'extra' : const.TYPE_MAP[extra_type](url=const.IVA_ASSET_URL % (extra.get('iva_id'), spoken_lang, bitrates, duration),
                                                                             title=extra.get('title'),
                                                                             year=avail.year,
                                                                             originally_available_at=avail,
                                                                             thumb=extra.get('thumb') or '')})
                    else:
                        Log('Skipping extra %s because type %s was not recognized.' % (extra.get('iva_id'), extra_type))

            # Sort the extras, making sure the primary trailer is first.
            extras.sort(key=lambda e: const.TYPE_ORDER.index(e['type']))

            # If our primary trailer is in English but the library language is something else, see if we can do better.
            if len(extras) > 0 and lang != Locale.Language.English and extras[0]['lang'] == Locale.Language.English:
                lang_matches = [t for t in xml.xpath('//extra') if t.get('type') == 'trailer' and const.IVA_LANGUAGES.get(int(t.get('subtitle_lang_code') or -1)) == lang]
                lang_matches += [t for t in xml.xpath('//extra') if t.get('type') == 'trailer' and const.IVA_LANGUAGES.get(int(t.get('lang_code') or -1)) == lang]
                if len(lang_matches) > 0:
                    extra = lang_matches[0]
                    spoken_lang = const.IVA_LANGUAGES.get(int(extra.get('lang_code') or -1)) or Locale.Language.Unknown
                    extras[0]['lang'] = spoken_lang
                    extras[0]['extra'].url = const.IVA_ASSET_URL % (extra.get('iva_id'), spoken_lang, extra.get('bitrates') or '', int(extra.get('duration') or 0))
                    extras[0]['extra'].thumb = extra.get('thumb') or ''
                    Log('Adding trailer with spoken language %s and subtitled langauge %s to match library language.' % (spoken_lang, const.IVA_LANGUAGES.get(int(extra.get('subtitle_lang_code') or -1)) or Locale.Language.Unknown))

            # Clean up the found extras.
            extras = [self.scrub_extra(extra, media_title) for extra in extras]

            count_to_load = int(Prefs['extras.max']) - len(metadata.extras)
            # Add them in the right order to the metadata.extras list.
            for i, extra in enumerate(extras):
                if (Prefs['extras.seq'] == 'Все источники') and i >= int(Prefs['extras.max']):
                    break
                elif (Prefs['extras.seq'] != 'Все источники') and i >= count_to_load:
                    break
                else:
                    metadata.extras.add(extra['extra'])

            Log('Added %d of %d extras.' % (len(metadata.extras), len(xml.xpath('//extra'))))
        except urllib2.HTTPError, e:
            if e.code == 403:
                Log('Skipping online extra lookup (an active Plex Pass is required).')

    def scrub_extra(self, extra, media_title):
        e = extra['extra']
        # Remove the "Movie Title: " from non-trailer extra titles.
        if media_title is not None:
            r = re.compile(media_title + ': ', re.IGNORECASE)
            e.title = r.sub('', e.title)
        # Remove the "Movie Title Scene: " from SceneOrSample extra titles.
        if media_title is not None:
            r = re.compile(media_title + ' Scene: ', re.IGNORECASE)
            e.title = r.sub('', e.title)
        # Capitalise UK correctly.
        e.title = e.title.replace('Uk', 'UK')

        return extra