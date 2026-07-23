$(window).on('load', function() {
  var documentSettings = {};

  // Some constants, such as default settings
  const CHAPTER_ZOOM = 15;

  // First, try reading Options.csv
  $.get('csv/Options.csv?time=' + Date.now(), function(options) {

    $.get('csv/Chapters.csv?time=' + Date.now(), function(chapters) {
      initMap(
        $.csv.toObjects(options),
        $.csv.toObjects(chapters)
      )
    }).fail(function(e) { alert('Found Options.csv, but could not read Chapters.csv') });

  // If not available, try from the Google Sheet
  }).fail(function(e) {

    var parse = function(res) {
      return Papa.parse(Papa.unparse(res[0].values), {header: true} ).data;
    }

    // First, try reading data from the Google Sheet
    if (typeof googleDocURL !== 'undefined' && googleDocURL) {

      if (typeof googleApiKey !== 'undefined' && googleApiKey) {

        var apiUrl = 'https://sheets.googleapis.com/v4/spreadsheets/'
        var spreadsheetId = googleDocURL.split('/d/')[1].split('/')[0];

        $.when(
          $.getJSON(apiUrl + spreadsheetId + '/values/Options?key=' + googleApiKey),
          $.getJSON(apiUrl + spreadsheetId + '/values/Chapters?key=' + googleApiKey),
        ).then(function(options, chapters) {
          initMap(parse(options), parse(chapters))
        })

      } else {
        alert('You load data from a Google Sheet, you need to add a free Google API key')
      }

    } else {
      alert('You need to specify a valid Google Sheet (googleDocURL)')
    }

  })

  function createDocumentSettings(settings) {
    for (var i in settings) {
      var setting = settings[i];
      documentSettings[setting.Setting] = setting.Customize;
    }
  }

  function getSetting(s) {
    return documentSettings[constants[s]];
  }

  function trySetting(s, def) {
    s = getSetting(s);
    if (!s || s.trim() === '') { return def; }
    return s;
  }

  function addBaseMap() {
    var basemap = trySetting('_tileProvider', 'Stamen.TonerLite');
    L.tileLayer.provider(basemap, {
      maxZoom: 18,
      apiKey: trySetting('_tileProviderApiKey', ''),
      apikey: trySetting('_tileProviderApiKey', ''),
      key: trySetting('_tileProviderApiKey', ''),
      accessToken: trySetting('_tileProviderApiKey', '')
    }).addTo(map);
  }

  function initMap(options, chapters) {
    createDocumentSettings(options);

    var chapterContainerMargin = 70;

    document.title = getSetting('_mapTitle');
    $('#header').append('<h1>' + (getSetting('_mapTitle') || '') + '</h1>');
    $('#header').append('<h2>' + (getSetting('_mapSubtitle') || '') + '</h2>');

    $.get('https://api.github.com/repos/stephend-csu/newspaper-v3/commits?path=csv/Chapters.csv&page=1&per_page=1', function(data) {
        if (data && data.length > 0) {
            var date = new Date(data[0].commit.committer.date);
            var formattedDate = date.toLocaleString('en-US', { timeZone: 'America/Los_Angeles', year: 'numeric', month: 'numeric', day: 'numeric', hour: 'numeric', minute: '2-digit', second: '2-digit' });
            $('#header').append('<h3 style="font-weight: normal; margin-top: 5px; color: #888;">Updated: ' + formattedDate + ' PST</h3>');
        }
    });

    if (getSetting('_mapLogo')) {
      $('#logo').append('<img src="' + getSetting('_mapLogo') + '" />');
      $('#top').css('height', '60px');
    } else {
      $('#logo').css('display', 'none');
      $('#header').css('padding-top', '25px');
    }

    addBaseMap();

    if (getSetting('_zoomControls') !== 'off') {
      L.control.zoom({
        position: getSetting('_zoomControls')
      }).addTo(map);
    }

    var markers = [];

    var markActiveColor = function(k) {
      for (var i = 0; i < markers.length; i++) {
        if (markers[i] && markers[i]._icon) {
          markers[i]._icon.className = markers[i]._icon.className.replace(' marker-active', '');

          if (i == k) {
            markers[k]._icon.className += ' marker-active';
          }
        }
      }
    }

    var pixelsAbove = [];
    var chapterCount = 0;

    var currentlyInFocus;
    var overlay;
    var geoJsonOverlay;

    var uniqueNewspapers = [];
    var notFoundAddresses = [];
    for (var i = 0; i < chapters.length; i++) {
        if (chapters[i]['Newspapers']) {
            var papers = chapters[i]['Newspapers'].split(' ');
            for (var j = 0; j < papers.length; j++) {
                if (papers[j] && uniqueNewspapers.indexOf(papers[j]) === -1) {
                    uniqueNewspapers.push(papers[j]);
                }
            }
        }
        if (chapters[i]['Chapter'] && chapters[i]['Chapter'].indexOf('(NOT FOUND)') !== -1) {
            notFoundAddresses.push(chapters[i]['Chapter']);
        }
    }

    var defaultColors = {'EBT': '#f44336', 'WSJ': '#9e9e9e', 'NYT': '#2196f3', 'SFC': '#ffeb3b'};
    var colorPalette = ['#f44336', '#e91e63', '#9c27b0', '#673ab7', '#3f51b5', '#2196f3', '#03a9f4', '#00bcd4', '#009688', '#4caf50', '#8bc34a', '#cddc39', '#ffeb3b', '#ffc107', '#ff9800', '#ff5722', '#795548', '#9e9e9e', '#607d8b', '#000000'];

    function getPaperColor(paper) {
        return localStorage.getItem('color_' + paper) || defaultColors[paper] || '#888888';
    }

    for (var i = 0; i < chapters.length; i++) {
      var c = chapters[i];

      if (c['Chapter'] && c['Chapter'].indexOf('(NOT FOUND)') !== -1) {
          markers.push(null);
          continue;
      }

      if ( !isNaN(parseFloat(c['Latitude'])) && !isNaN(parseFloat(c['Longitude']))) {
        var lat = parseFloat(c['Latitude']);
        var lon = parseFloat(c['Longitude']);

        chapterCount += 1;

        markers.push(
          L.marker([lat, lon], {
            icon: L.ExtraMarkers.icon({
              icon: 'fa-number',
              number: c['Marker'] === 'Numbered'
                ? chapterCount
                : (c['Marker'] === 'Plain'
                  ? ''
                  : c['Marker']), 
              markerColor: c['Marker Color'] || 'blue'
            }),
            opacity: c['Marker'] === 'Hidden' ? 0 : 0.9,
            interactive: c['Marker'] === 'Hidden' ? false : true,
          }
        ));

      } else {
        markers.push(null);
      }

      var container = $('<div></div>', {
        id: 'container' + i,
        class: 'chapter-container'
      });

      if (i === 0) {
        var colorPickerHtml = '<div class="color-picker-container"><h3>Newspaper Colors</h3>';
        for (var n = 0; n < uniqueNewspapers.length; n++) {
            var paper = uniqueNewspapers[n];
            var currentColor = getPaperColor(paper);
            colorPickerHtml += '<div class="color-row"><strong>' + paper + '</strong><div class="color-options">';
            for (var p = 0; p < colorPalette.length; p++) {
                var col = colorPalette[p];
                var selClass = (col === currentColor) ? ' selected' : '';
                colorPickerHtml += '<div class="color-circle' + selClass + '" data-paper="' + paper + '" data-color="' + col + '" style="background-color: ' + col + ';"></div>';
            }
            colorPickerHtml += '</div></div>';
        }
        if (notFoundAddresses.length > 0) {
            colorPickerHtml += '<h3>Could not find</h3><ul>';
            for (var nf = 0; nf < notFoundAddresses.length; nf++) {
                colorPickerHtml += '<li>' + notFoundAddresses[nf] + '</li>';
            }
            colorPickerHtml += '</ul>';
        }
        colorPickerHtml += '</div>';
        container.append(colorPickerHtml);
      } else if (i === 1) {
        var summaryDiv = $('<div id="route-summary"></div>');
        container.append(summaryDiv);
        $.getJSON('csv/upload_meta.json?time=' + Date.now(), function(meta) {
            var html = '<h3>Route Summary</h3>';
            html += '<p class="upload-meta">Addresses found: ' + (meta.found || 0) + '</p>';
            html += '<p class="upload-meta">Addresses not found: ' + (meta.not_found || 0) + '</p>';
            summaryDiv.html(html);
        }).fail(function() {
            // silently skip
        });
      } else {
        var addressRaw = c['Chapter'] || '';
        var commaIdx = addressRaw.indexOf(',');
        var addressStr = commaIdx !== -1 ? addressRaw.substring(0, commaIdx) : addressRaw;
        
        var addressWords = addressStr.toLowerCase().split(' ');
        var formattedAddress = [];
        for (var w = 0; w < addressWords.length; w++) {
            if (addressWords[w]) {
                formattedAddress.push(addressWords[w].charAt(0).toUpperCase() + addressWords[w].slice(1));
            }
        }
        formattedAddress = formattedAddress.join(' ');

        var mapsLink = c['Maps Link'] || ('https://www.google.com/maps/search/?api=1&query=' + encodeURIComponent(formattedAddress));

        container.append('<p class="chapter-header"><a href="' + mapsLink + '" target="_blank" style="color: inherit; text-decoration: none;">' + formattedAddress + '</a></p>');

        if (c['Newspapers'] && c['Newspapers'].trim().length > 0) {
            var papers = c['Newspapers'].split(' ');
            var badgesHtml = '<div class="newspaper-badges">';
            for (var p = 0; p < papers.length; p++) {
                if (papers[p]) {
                    var col = getPaperColor(papers[p]);
                    var lightCol = col + '40';
                    badgesHtml += '<span class="newspaper-badge" data-paper="' + papers[p] + '" style="background-color: ' + lightCol + '; color: ' + col + ';">' + papers[p] + '</span>';
                }
            }
            badgesHtml += '</div>';
            container.append(badgesHtml);
        }

        if (c['Miles To Next'] && c['Miles To Next'].trim().length > 0) {
            container.append('<p class="miles-to-next">' + c['Miles To Next'] + ' mi to next</p>');
        }

        if (i < chapters.length - 1) {
            var visitedClass = sessionStorage.getItem('visited_' + i) === 'true' ? ' visited' : '';
            container.append('<button class="next-btn' + visitedClass + '" data-index="' + i + '">Next ▼</button>');
        }

        var media = null;
        var mediaContainer = null;
        var source = '';
        if (c['Media Credit Link']) {
          source = $('<a>', {
            text: c['Media Credit'],
            href: c['Media Credit Link'],
            target: "_blank",
            class: 'source'
          });
        } else {
          source = $('<span>', {
            text: c['Media Credit'],
            class: 'source'
          });
        }

        if (c['Media Link'] && c['Media Link'].indexOf('youtube.com/') > -1) {
          media = $('<iframe></iframe>', {
            src: c['Media Link'],
            width: '100%',
            height: '100%',
            frameborder: '0',
            allow: 'autoplay; encrypted-media',
            allowfullscreen: 'allowfullscreen',
          });

          mediaContainer = $('<div></div>', {
            class: 'img-container'
          }).append(media).after(source);
        }

        var mediaTypes = {
          'jpg': 'img', 'jpeg': 'img', 'png': 'img', 'tiff': 'img', 'gif': 'img',
          'mp3': 'audio', 'ogg': 'audio', 'wav': 'audio',
        };

        var mediaExt = c['Media Link'] ? c['Media Link'].split('.').pop().toLowerCase() : '';
        var mediaType = mediaTypes[mediaExt];

        if (mediaType) {
          media = $('<' + mediaType + '>', {
            src: c['Media Link'],
            controls: mediaType === 'audio' ? 'controls' : '',
            alt: c['Chapter']
          });

          var enableLightbox = getSetting('_enableLightbox') === 'yes' ? true : false;
          if (enableLightbox && mediaType === 'img') {
            var lightboxWrapper = $('<a></a>', {
              'data-lightbox': c['Media Link'],
              'href': c['Media Link'],
              'data-title': c['Chapter'],
              'data-alt': c['Chapter'],
            });
            media = lightboxWrapper.append(media);
          }

          mediaContainer = $('<div></div>', {
            class: mediaType + '-container'
          }).append(media).after(source);
        }

        if (mediaContainer) {
            container.append(mediaContainer);
        }
        if (media && source.text()) {
            container.append(source);
        }

        if (c['Description'] && c['Description'].trim().length > 0) {
            container.append('<p class="description">' + c['Description'] + '</p>');
        }
      }

      $('#contents').append(container);

    }

    changeAttribution();

    var imgContainerHeight = parseInt(getSetting('_imgContainerHeight'));
    if (imgContainerHeight > 0) {
      $('.img-container').css({
        'height': imgContainerHeight + 'px',
        'max-height': imgContainerHeight + 'px',
      });
    }

    pixelsAbove[0] = -100;
    for (var i = 1; i < chapters.length; i++) {
      var prevContainer = $('div#container' + (i-1));
      var prevHeight = prevContainer.length ? prevContainer.height() : 0;
      pixelsAbove[i] = pixelsAbove[i-1] + prevHeight + (prevContainer.length ? chapterContainerMargin : 0);
    }
    pixelsAbove.push(Number.MAX_VALUE);

    $('div#contents').scroll(function() {
      var currentPosition = $(this).scrollTop();

      if (currentPosition < 200) {
        $('#title').css('opacity', 1 - Math.min(1, currentPosition / 100));
      }

      for (var i = 0; i < pixelsAbove.length - 1; i++) {

        if ( currentPosition >= pixelsAbove[i]
          && currentPosition < (pixelsAbove[i+1] - 2 * chapterContainerMargin)
          && currentlyInFocus != i
        ) {

          location.hash = i + 1;

          $('.chapter-container').removeClass("in-focus").addClass("out-focus");
          $('div#container' + i).addClass("in-focus").removeClass("out-focus");

          currentlyInFocus = i;
          markActiveColor(currentlyInFocus);

          if (overlay && map.hasLayer(overlay)) {
            map.removeLayer(overlay);
          }

          if (geoJsonOverlay && map.hasLayer(geoJsonOverlay)) {
            map.removeLayer(geoJsonOverlay);
          }

          var c = chapters[i];

          if (c && c['Overlay']) {

            var opacity = parseFloat(c['Overlay Transparency']) || 1;
            var url = c['Overlay'];

            if (url.split('.').pop() === 'geojson') {
              $.getJSON(url, function(geojson) {
                overlay = L.geoJson(geojson, {
                  style: function(feature) {
                    return {
                      fillColor: feature.properties.fillColor || '#ffffff',
                      weight: feature.properties.weight || 1,
                      opacity: feature.properties.opacity || opacity,
                      color: feature.properties.color || '#cccccc',
                      fillOpacity: feature.properties.fillOpacity || 0.5,
                    }
                  }
                }).addTo(map);
              });
            } else {
              overlay = L.tileLayer(c['Overlay'], { opacity: opacity }).addTo(map);
            }

          }

          if (c && c['GeoJSON Overlay']) {
            $.getJSON(c['GeoJSON Overlay'], function(geojson) {

              var props = {};

              if (c['GeoJSON Feature Properties']) {
                var propsArray = c['GeoJSON Feature Properties'].split(';');
                var props = {};
                for (var p in propsArray) {
                  if (propsArray[p].split(':').length === 2) {
                    props[ propsArray[p].split(':')[0].trim() ] = propsArray[p].split(':')[1].trim();
                  }
                }
              }

              geoJsonOverlay = L.geoJson(geojson, {
                style: function(feature) {
                  return {
                    fillColor: feature.properties.fillColor || props.fillColor || '#ffffff',
                    weight: feature.properties.weight || props.weight || 1,
                    opacity: feature.properties.opacity || props.opacity || 0.5,
                    color: feature.properties.color || props.color || '#cccccc',
                    fillOpacity: feature.properties.fillOpacity || props.fillOpacity || 0.5,
                  }
                }
              }).addTo(map);
            });
          }

          if (c && c['Latitude'] && c['Longitude']) {
            var zoom = c['Zoom'] ? c['Zoom'] : CHAPTER_ZOOM;
            map.flyTo([c['Latitude'], c['Longitude']], zoom, {
              animate: true,
              duration: 2,
            });
          }

          break;
        }
      }
    });


    $('#contents').append(" \
      <div id='space-at-the-bottom'> \
        <a href='#top'>  \
          <i class='fa fa-chevron-up'></i></br> \
          <small>Top</small>  \
        </a> \
      </div> \
    ");

    $("<style>")
      .prop("type", "text/css")
      .html("\
      #narration, #title {\
        background-color: " + trySetting('_narrativeBackground', 'white') + "; \
        color: " + trySetting('_narrativeText', 'black') + "; \
      }\
      a, a:visited, a:hover {\
        color: " + trySetting('_narrativeLink', 'blue') + " \
      }\
      .in-focus {\
        background-color: " + trySetting('_narrativeActive', '#f0f0f0') + " \
      }")
      .appendTo("head");


    var endPixels = parseInt(getSetting('_pixelsAfterFinalChapter'));
    if (endPixels > 100) {
      $('#space-at-the-bottom').css({
        'height': (endPixels / 2) + 'px',
        'padding-top': (endPixels / 2) + 'px',
      });
    }

    var bounds = [];
    for (var i = 0; i < markers.length; i++) {
      if (markers[i]) {
        markers[i].addTo(map);
        markers[i]['_pixelsAbove'] = pixelsAbove[i];
        markers[i].on('click', function() {
          var pixels = parseInt($(this)[0]['_pixelsAbove']) + 5;
          $('div#contents').animate({
            scrollTop: pixels + 'px'});
        });
        bounds.push(markers[i].getLatLng());
      }
    }
    if (bounds.length > 0) {
      map.fitBounds(bounds);
    }

    $('#map, #narration, #title').css('visibility', 'visible');
    $('div.loader').css('visibility', 'hidden');

    $('div#container0').addClass("in-focus");
    $('div#contents').animate({scrollTop: '1px'});

    if (parseInt(location.hash.substr(1))) {
      var containerId = parseInt( location.hash.substr(1) ) - 1;
      var targetContainer = $('#container' + containerId);
      if (targetContainer.length) {
        $('#contents').animate({
          scrollTop: targetContainer.offset().top
        }, 2000);
      }
    }

    var ga = getSetting('_googleAnalytics');
    if ( ga && ga.length >= 10 ) {
      var gaScript = document.createElement('script');
      gaScript.setAttribute('src','https://www.googletagmanager.com/gtag/js?id=' + ga);
      document.head.appendChild(gaScript);

      window.dataLayer = window.dataLayer || [];
      function gtag(){dataLayer.push(arguments);}
      gtag('js', new Date());
      gtag('config', ga);
    }


  }

  function changeAttribution() {
    var attributionControl = $('.leaflet-control-attribution');
    if (!attributionControl.length) return;
    
    var attributionHTML = attributionControl[0].innerHTML;
    var credit = 'View <a href="'
      + (typeof googleDocURL !== 'undefined' && googleDocURL ? googleDocURL : './csv/Chapters.csv')
      + '" target="_blank">data</a>';

    var name = getSetting('_authorName');
    var url = getSetting('_authorURL');

    if (name && url) {
      if (url.indexOf('@') > 0) { url = 'mailto:' + url; }
      credit += ' by <a href="' + url + '">' + name + '</a> | ';
    } else if (name) {
      credit += ' by ' + name + ' | ';
    } else {
      credit += ' | ';
    }

    credit += 'View <a href="' + getSetting('_githubRepo') + '">code</a>';
    if (getSetting('_codeCredit')) credit += ' by ' + getSetting('_codeCredit');
    credit += ' with ';
    attributionControl[0].innerHTML = credit + attributionHTML;
  }

  // Click handler for color circles
  $(document).on('click', '.color-circle', function() {
    var paper = $(this).data('paper');
    var color = $(this).data('color');
    
    // update localStorage
    localStorage.setItem('color_' + paper, color);
    
    // update classes
    $('.color-circle[data-paper="' + paper + '"]').removeClass('selected');
    $(this).addClass('selected');
    
    // update newspaper badges
    $('.newspaper-badge[data-paper="' + paper + '"]').each(function() {
      var lightCol = color + '40';
      $(this).css('background-color', lightCol);
      $(this).css('color', color);
    });
  });

  // Click handler for next button
  $(document).on('click', '.next-btn', function() {
      var idx = parseInt($(this).data('index'));
      var nextContainer = $('#container' + (idx + 1));
      if (nextContainer.length) {
          $('#contents').animate({ scrollTop: $('#contents').scrollTop() + nextContainer.position().top - 10 }, 500);
      }
      sessionStorage.setItem('visited_' + idx, 'true');
      $(this).addClass('visited');
  });

});
