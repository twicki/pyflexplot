"""Map axes."""
from __future__ import annotations

# Standard library
import dataclasses as dc
import warnings
from typing import Any
from typing import Dict
from typing import List
from typing import Mapping
from typing import Optional
from typing import Sequence
from typing import Tuple
from typing import Union

# Third-party
import cartopy
import matplotlib as mpl
import numpy as np
from cartopy.io.shapereader import Record  # type: ignore
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from matplotlib.text import Text

# Local
from ..input.field import Field
from ..utils.exceptions import TooWideRefDistIndicatorError
from ..utils.logging import log
from ..utils.summarize import summarizable
from ..utils.typing import ColorType
from ..utils.typing import RectType
from .coord_trans import CoordinateTransformer
from .domain import Domain
from .proj_bbox import Projections
from .ref_dist_indicator import RefDistIndConfig
from .ref_dist_indicator import ReferenceDistanceIndicator


# pylint: disable=E0213  # no-self-argument (validators)
# pylint: disable=?R0902  # too-many-instance-attributes
@summarizable
@dc.dataclass
class MapAxesConfig:
    """Configuration of ``MapAxesPlot``.

    Args:
        all_capital_cities (optional): Show all capital cities, regardless of
            population.
        aspect (optional): Aspect ratio; width by height.

        d_lat_grid (optional): Latitudinal grid line interval.

        d_lon_grid (optional): Longitudinal grid line interval.

        exclude_cities (optional): Exclude cities by name.

        geo_res (optional): Resolution of geographic map elements.

        geo_res_cities (optional): Scale for cities shown on map. Defaults to
            ``geo_res``.

        geo_res_rivers (optional): Scale for rivers shown on map. Defaults to
            ``geo_res``.

        lang (optional): Language; 'en' for English, 'de' for German.

        lw_frame (optional): Line width of frames.

        min_city_pop (optional): Minimum population of cities shown.

        only_capital_cities (optional): Only show capital cities.

        projection (optional): Map projection. Defaults to that of the input
            data.

        ref_dist_config (optional): Reference distance indicator setup.

        ref_dist_on (optional): Whether to add a reference distance indicator.

        scale_fact (optional): Scaling factor for plot elements (fonts, lines,
            etc.)

    """

    all_capital_cities: bool = True
    aspect: float = 1.0
    d_lat_grid: float = 10.0
    d_lon_grid: float = 10.0
    exclude_cities: list[str] = dc.field(default_factory=list)
    geo_res: str = "50m"
    geo_res_cities: str = "none"
    geo_res_rivers: str = "none"
    lang: str = "en"
    lw_frame: float = 1.0
    min_city_pop: int = 0
    only_capital_cities: bool = False
    projection: str = "data"
    ref_dist_config: Optional[Union[RefDistIndConfig, Mapping[str, Any]]] = None
    ref_dist_on: bool = True
    scale_fact: float = 1.0

    def __post_init__(self) -> None:
        # geo_res*
        if self.geo_res_cities == "none":
            self.geo_res_cities = self.geo_res
        if self.geo_res_rivers == "none":
            self.geo_res_rivers = self.geo_res

        # ref_dist_config
        if self.ref_dist_config is None:
            self.ref_dist_config = RefDistIndConfig()
        elif isinstance(self.ref_dist_config, Mapping):
            # Passed a dict as argument; turn into ``RefDistIndConfig``
            self.ref_dist_config = RefDistIndConfig(**self.ref_dist_config)
        assert isinstance(self.ref_dist_config, RefDistIndConfig)
        self.ref_dist_config = self.ref_dist_config.scale(self.scale_fact)


# pylint: disable=R0902  # too-many-instance-attributes
@summarizable(
    attrs=[
        "config",
        "domain",
        "field",
        "rect",
        "trans",
        "elements",
    ],
)
class MapAxes:
    """Map plot axes for regular lat/lon data."""

    def __init__(
        self,
        *,
        config: MapAxesConfig,
        field: Field,
        domain: Domain,
        fig: Figure,
        rect: RectType,
    ) -> None:
        """Create an instance of ``MapAxes``.

        Args:
            fig: Figure to which to map axes is added.

            rect: Position of map plot panel in figure coordinates.

            field: Field object.

            domain: Domain object.

            config: Map axes setup.

        """
        self.config: MapAxesConfig = config
        self.field: Field = field
        self.domain: Domain = domain
        self.fig: Figure = fig
        self.rect: RectType = rect

        self.element_handles: List[Tuple[str, Any]] = []
        self.elements: List[Dict[str, Any]] = []

        clon, _ = domain.get_center()
        self._clon: float = clon
        self.projs: Projections = Projections.from_proj_data(field.proj, clon=clon)

        self._water_color: ColorType = "lightskyblue"

        self.zorder: Dict[str, int]
        self._init_zorder()

        # SR_TMP <<< TODO Clean this up!
        def _create_ax(
            fig: Figure,
            rect: RectType,
            domain: Domain,
        ) -> Axes:
            """Initialize Axes."""
            with warnings.catch_warnings():
                warnings.filterwarnings(
                    "ignore",
                    category=RuntimeWarning,
                    message="numpy.ufunc size changed",
                )
                ax: Axes = fig.add_axes(rect, projection=self.projs.map)
            ax.set_adjustable("datalim")
            ax.spines["geo"].set_edgecolor("none")
            ax.set_aspect("auto")
            bbox = domain.get_bbox(ax, self.projs, "map")
            ax.set_extent(bbox, self.projs.map)
            return ax

        self.ax: Axes = _create_ax(
            self.fig,
            self.rect,
            self.domain,
        )

        self.trans = CoordinateTransformer(
            trans_axes=self.ax.transAxes,
            trans_data=self.ax.transData,
            proj_geo=self.projs.geo,
            proj_map=self.projs.map,
            proj_data=self.projs.data,
        )

        self.ref_dist_box: Optional[
            ReferenceDistanceIndicator
        ] = self._init_ref_dist_box()

        self._ax_add_grid()
        self._ax_add_geography()
        self._ax_add_data_domain_outline()
        self._ax_add_frame()

    def add_marker(
        self,
        *,
        p_lon: float,
        p_lat: float,
        marker: str,
        zorder: Optional[int] = None,
        **kwargs,
    ) -> Sequence[Line2D]:
        """Add a marker at a location in natural coordinates."""
        # pylint: disable=E0633  # unpacking-non-sequence
        p_lon, p_lat = self.trans.geo_to_data(p_lon, p_lat)
        if zorder is None:
            zorder = self.zorder["marker"]
        handle = self.ax.plot(
            p_lon,
            p_lat,
            marker=marker,
            transform=self.trans.proj_data,
            zorder=zorder,
            **kwargs,
        )
        self.element_handles.append(handle)
        self.elements.append(
            {
                "element_type": "marker",
                "p_lon": p_lon,
                "p_lat": p_lat,
                "marker": marker,
                "transform": f"{type(self.trans.proj_data).__name__} instance",
                "zorder": zorder,
                **kwargs,
            }
        )
        return handle

    def add_text(
        self,
        p_lon: float,
        p_lat: float,
        s: str,
        *,
        zorder: Optional[int] = None,
        **kwargs,
    ) -> Text:
        """Add text at a geographical point.

        Args:
            p_lon: Point longitude.

            p_lat: Point latitude.

            s: Text string.

            dx: Horizontal offset in unit distances.

            dy (optional): Vertical offset in unit distances.

            zorder (optional): Vertical order. Defaults to "geo_lower".

            **kwargs: Additional keyword arguments for ``ax.text``.

        """
        if zorder is None:
            zorder = self.zorder["geo_lower"]
        kwargs_default = {"xytext": (5, 1), "textcoords": "offset points"}
        kwargs = {**kwargs_default, **kwargs}
        # pylint: disable=W0212  # protected-access
        # pylint: disable=E1101  # no-member [pylint 2.7.4]
        # (pylint 2.7.4 does not support dataclasses.field)
        transform = self.trans.proj_geo._as_mpl_transform(self.ax)
        # -> see https://stackoverflow.com/a/25421922/4419816
        handle = self.ax.annotate(
            s, xy=(p_lon, p_lat), xycoords=transform, zorder=zorder, **kwargs
        )
        self.element_handles.append(handle)
        self.elements.append(
            {
                "element_type": "text",
                "s": s,
                "xy": (p_lon, p_lat),
                "xycoords": f"{type(transform).__name__} instance",
                "zorder": zorder,
                **kwargs,
            }
        )
        return handle

    def __repr__(self) -> str:
        return f"{type(self).__name__}(<TODO>)"  # SR_TODO

    def _init_zorder(self) -> None:
        """Determine zorder of unique plot elements, from low to high."""
        zorders_const = [
            "frames",
            "marker",
            "grid",
            "geo_upper",
            "geo_lower",
            "fld",
            "lowest",
        ][::-1]
        d0, dz = 1, 1
        self.zorder = {name: d0 + idx * dz for idx, name in enumerate(zorders_const)}

    def _init_ref_dist_box(self) -> Optional[ReferenceDistanceIndicator]:
        """Initialize the reference distance indicator (if activated)."""
        if not self.config.ref_dist_on:
            return None
        assert isinstance(self.config.ref_dist_config, RefDistIndConfig)  # mypy
        try:
            ref_dist_box = ReferenceDistanceIndicator(
                config=self.config.ref_dist_config,
                axes_to_geo=self.trans.axes_to_geo,
            )
        except TooWideRefDistIndicatorError as e:
            msg = f"error adding reference distance indicator (too wide {e})"
            log(wrn=msg)
            return None
        else:
            ref_dist_box.add_to(self.ax, zorder=self.zorder["grid"])
        return ref_dist_box

    def _ax_add_grid(self) -> None:
        """Show grid lines on map."""
        gl = self.ax.gridlines(
            linestyle=":", linewidth=1, color="black", zorder=self.zorder["grid"]
        )
        gl.xlocator = mpl.ticker.FixedLocator(
            np.arange(-180, 180, self.config.d_lon_grid)
        )
        gl.ylocator = mpl.ticker.FixedLocator(
            np.arange(-90, 90.1, self.config.d_lat_grid)
        )

    def _ax_add_geography(self) -> None:
        """Add geographic elements: coasts, countries, colors, etc."""
        self.ax.coastlines(resolution=self.config.geo_res)
        self.ax.patch.set_facecolor(self._water_color)
        self._ax_add_countries("lowest", rasterized=True)
        self._ax_add_lakes("lowest", rasterized=True)
        self._ax_add_rivers("lowest", rasterized=True)
        self._ax_add_countries("geo_lower", rasterized=True)
        self._ax_add_countries("geo_upper", rasterized=True)
        self._ax_add_cities("geo_upper", rasterized=False)

    def _ax_add_countries(self, zorder_key: str, rasterized: bool = False) -> None:
        edgecolor = "white" if zorder_key == "geo_lower" else "black"
        facecolor = "white" if zorder_key == "lowest" else "none"
        linewidth = 1 / 3 if zorder_key == "geo_upper" else 1
        self.ax.add_feature(
            cartopy.feature.NaturalEarthFeature(
                category="cultural",
                name="admin_0_countries_lakes",
                scale=self.config.geo_res,
                edgecolor=edgecolor,
                facecolor=facecolor,
                linewidth=linewidth * self.config.scale_fact,
                rasterized=rasterized,
            ),
            zorder=self.zorder[zorder_key],
            rasterized=rasterized,
        )

    def _ax_add_lakes(self, zorder_key: str, rasterized: bool = False) -> None:
        self.ax.add_feature(
            cartopy.feature.NaturalEarthFeature(
                category="physical",
                name="lakes",
                scale=self.config.geo_res,
                edgecolor="none",
                facecolor=self._water_color,
                rasterized=rasterized,
            ),
            zorder=self.zorder[zorder_key],
            rasterized=rasterized,
        )
        if self.config.geo_res == "10m":
            self.ax.add_feature(
                cartopy.feature.NaturalEarthFeature(
                    category="physical",
                    name="lakes_europe",
                    scale=self.config.geo_res,
                    edgecolor="none",
                    facecolor=self._water_color,
                    rasterized=rasterized,
                ),
                zorder=self.zorder[zorder_key],
                rasterized=rasterized,
            )

    def _ax_add_rivers(self, zorder_key: str, rasterized: bool = False) -> None:
        linewidth = {"lowest": 1, "geo_lower": 1, "geo_upper": 2 / 3}[zorder_key]
        # Note:
        #  - Bug in Cartopy with recent shapefiles triggers errors (NULL geometry)
        #    -> PR: https://github.com/SciTools/cartopy/pull/1411
        #  - Issue fixed in Cartopy 0.18.0

        major_rivers = cartopy.feature.NaturalEarthFeature(
            category="physical",
            name="rivers_lake_centerlines",
            scale=self.config.geo_res,
            edgecolor=self._water_color,
            facecolor=(0, 0, 0, 0),
            linewidth=linewidth,
            rasterized=rasterized,
        )
        self.ax.add_feature(major_rivers, zorder=self.zorder[zorder_key])

        if self.config.geo_res_rivers == "10m":
            minor_rivers = cartopy.feature.NaturalEarthFeature(
                category="physical",
                name="rivers_europe",
                scale=self.config.geo_res,
                edgecolor=self._water_color,
                facecolor=(0, 0, 0, 0),
                linewidth=linewidth,
                rasterized=rasterized,
            )
            self.ax.add_feature(minor_rivers, zorder=self.zorder[zorder_key])

    # pylint: disable=R0914  # too-many-locals (>15)
    # pylint: disable=R0915  # too-many-statements (>50)
    def _ax_add_cities(self, zorder_key: str, rasterized: bool = False) -> None:
        """Add major cities, incl. all capitals."""
        all_capitals = self.config.all_capital_cities
        only_capitals = self.config.only_capital_cities
        excluded_names = np.array(self.config.exclude_cities, dtype=np.str_)

        def get_name(city: Record) -> str:
            """Get city name in current language, hand-correcting some."""
            name = city.attributes[f"name_{self.config.lang}"]
            if name.startswith("Freiburg im ") and name.endswith("echtland"):
                name = "Freiburg"
            return name

        def is_capital(city: Record) -> bool:
            """Determine whether a city is a capital."""
            return city.attributes["FEATURECLA"].startswith("Admin-0 capital")

        def get_population(city: Record) -> int:
            """Get city population."""
            return city.attributes["GN_POP"]

        def get_lon(city: Record) -> np.ndarray:
            """Get the city longitude."""
            return city.geometry.x

        def get_lat(city: Record) -> np.ndarray:
            """Get the city latitude."""
            return city.geometry.y

        def is_in_domain(px_ax: float, py_ax: float) -> bool:
            """Check if point is in domain."""
            return 0.0 <= px_ax <= 1.0 and 0.0 <= py_ax <= 1.0

        def is_behind_ref_dist_box(px_ax: float, py_ax: float) -> bool:
            """Check if point is behind reference distance box."""
            if self.ref_dist_box is None:
                return False
            return (
                self.ref_dist_box.x0_box <= px_ax <= self.ref_dist_box.x1_box
                and self.ref_dist_box.y0_box <= py_ax <= self.ref_dist_box.y1_box
            )

        np_get_name = np.frompyfunc(get_name, 1, 1)
        np_is_capital = np.frompyfunc(is_capital, 1, 1)
        np_get_population = np.frompyfunc(get_population, 1, 1)
        np_get_lon = np.frompyfunc(get_lon, 1, 1)
        np_get_lat = np.frompyfunc(get_lat, 1, 1)
        np_is_in_domain = np.frompyfunc(is_in_domain, 2, 1)
        np_is_behind_ref_dist_box = np.frompyfunc(is_behind_ref_dist_box, 2, 1)

        # src: https://www.naturalearthdata.com/downloads/50m-cultural-vectors/...
        # .../50m-populated-places/lk
        cities = np.array(
            list(
                cartopy.io.shapereader.Reader(
                    cartopy.io.shapereader.natural_earth(
                        category="cultural",
                        name="populated_places",
                        resolution=self.config.geo_res_cities,
                    )
                ).records()
            )
        )

        # Select cities of interest
        capitals = np_is_capital(cities).astype(np.bool_)
        populations = np_get_population(cities).astype(np.int32)
        if all_capitals and only_capitals:
            selected = capitals
        elif all_capitals and not only_capitals:
            selected = capitals | (populations > self.config.min_city_pop)
        elif not all_capitals and only_capitals:
            selected = capitals & (populations > self.config.min_city_pop)
        elif not all_capitals and not only_capitals:
            selected = populations > self.config.min_city_pop
        cities = cities[selected]

        # Pre-select cities in and around domain
        lons = np_get_lon(cities).astype(np.float32)
        lats = np_get_lat(cities).astype(np.float32)
        lon_min, lat_min, lon_max, lat_max = self._get_domain_bbox()
        in_domain = (
            (lons > lon_min) & (lons < lon_max) & (lats > lat_min) & (lats < lat_max)
        )
        cities = cities[in_domain]

        # Select visible cities
        lons = np_get_lon(cities).astype(np.float32)
        lats = np_get_lat(cities).astype(np.float32)
        # pylint: disable=E0633  # unpacking-non-sequence (false negative?!?)
        xs, ys = self.trans.geo_to_axes(lons, lats)
        in_domain = np_is_in_domain(xs, ys).astype(np.bool_)
        behind_ref_dist_box = np_is_behind_ref_dist_box(xs, ys).astype(np.bool_)
        visible = in_domain & ~behind_ref_dist_box
        cities = cities[visible]

        # Sort cities by name
        names = np_get_name(cities).astype(np.str_)
        sorted_inds = names.argsort()
        names = names[sorted_inds]
        cities = cities[sorted_inds]

        # Exclude certain cities by name
        excluded = np.in1d(names, excluded_names)
        cities = cities[~excluded]

        plot_domain = mpl.patches.Rectangle(
            xy=(0, 0), width=1.0, height=1.0, transform=self.ax.transAxes
        )
        for city in cities:
            lon, lat = city.geometry.x, city.geometry.y
            name = get_name(city)
            self.add_marker(
                p_lat=lat,
                p_lon=lon,
                marker="o",
                color="black",
                fillstyle="none",
                markeredgewidth=1 * self.config.scale_fact,
                markersize=3 * self.config.scale_fact,
                zorder=self.zorder[zorder_key],
                rasterized=rasterized,
            )
            text = self.add_text(
                lon,
                lat,
                name,
                va="center",
                size=9 * self.config.scale_fact,
                rasterized=rasterized,
            )
            # Note: `clip_on=True` doesn't work in cartopy v0.18
            text.set_clip_path(plot_domain)

    def _ax_add_data_domain_outline(self) -> None:
        """Add domain outlines to map plot."""
        lon0, lon1 = self.field.lon[[0, -1]]
        lat0, lat1 = self.field.lat[[0, -1]]
        xs = [lon0, lon1, lon1, lon0, lon0]
        ys = [lat0, lat0, lat1, lat1, lat0]
        self.ax.plot(xs, ys, transform=self.trans.proj_data, c="black", lw=1)

    def _ax_add_frame(self) -> None:
        """Draw frame around map plot."""
        self.ax.add_patch(
            mpl.patches.Rectangle(
                xy=(0, 0),
                width=1,
                height=1,
                transform=self.ax.transAxes,
                zorder=self.zorder["frames"],
                facecolor="none",
                edgecolor="black",
                linewidth=self.config.lw_frame,
                clip_on=False,
            ),
        )

    # pylint: disable=R0914  # too-many-locals (>15)
    # pylint: disable=E0633  # unpacking-non-sequence (false negative?!?)
    def _get_domain_bbox(
        self, n: int = 20, pad: float = 1.0
    ) -> tuple[float, float, float, float]:
        """Get ``(lon0, lat0, lon1, lat1)`` bounding box of domain."""
        trans = self.trans.axes_to_geo
        lons_s, lats_s = trans(np.linspace(0, 1, n), np.full([n], 0))
        lons_n, lats_n = trans(np.linspace(0, 1, n), np.full([n], 1))
        lons_w, lats_w = trans(np.full([n], 0), np.linspace(0, 1, n))
        lons_e, lats_e = trans(np.full([n], 1), np.linspace(0, 1, n))
        lon_min = min([lons_s.min(), lons_n.min(), lons_w.min(), lons_e.min()])
        lat_min = min([lats_s.min(), lats_n.min(), lats_w.min(), lats_e.min()])
        lon_max = max([lons_s.max(), lons_n.max(), lons_w.max(), lons_e.max()])
        lat_max = max([lats_s.max(), lats_n.max(), lats_w.max(), lats_e.max()])
        return (lon_min - pad, lat_min - pad, lon_max + pad, lat_max + pad)
